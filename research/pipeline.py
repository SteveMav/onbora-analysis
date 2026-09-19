"""Durable orchestration for one bounded company-research run."""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .gemini import GeminiResearchClient, GeminiServiceError, SummaryEvidence
from .lead_qualification import LeadEvidence, build_lead_qualification
from .models import EvidenceCapture, ResearchEvent, ResearchRun, RunEvidence, SourceAttempt
from .sector_segmentation import SectorEvidence, build_sector_segmentation
from .web_research import (
    PageFetcher,
    SearchHit,
    SearxngClient,
    build_query_plan,
    canonicalize_url,
    company_from_snapshot,
    rank_search_hit,
)


def _publisher(url: str) -> str:
    return (urlsplit(url).hostname or "").casefold().removeprefix("www.")[:255]


def _identity_status(evidence: list[RunEvidence]) -> str:
    usable = [item for item in evidence if item.verdict in {"Pertinente", "À vérifier"}]
    if not usable:
        return "not_found"
    for item in usable:
        joined = " ".join(item.reasons).casefold()
        has_name = "nom légal" in joined or "nom commercial" in joined
        has_strong_attribute = any(value in joined for value in ("rccm", "numéro fiscal", "adresse arsp"))
        if has_name and has_strong_attribute:
            return "confirmed"
    independent_publishers = {
        item.evidence.publisher
        for item in usable
        if item.evidence.relationship == "independent" and item.evidence.publisher
    }
    has_strong_attribute = any(
        any(value in " ".join(item.reasons).casefold() for value in ("rccm", "numéro fiscal", "adresse arsp"))
        for item in usable
    )
    if len(independent_publishers) >= 2 and has_strong_attribute:
        return "probable"
    return "ambiguous"


def execute_research_run(
    run: ResearchRun,
    *,
    search_client: SearxngClient | None = None,
    page_fetcher: PageFetcher | None = None,
    ai_client: GeminiResearchClient | None = None,
) -> ResearchRun:
    """Execute discovery, ranking, bounded fetching and evidence persistence."""
    search_client = search_client or SearxngClient()
    page_fetcher = page_fetcher or PageFetcher()
    ai_client = ai_client or GeminiResearchClient.from_settings()
    company = company_from_snapshot(run.seed_snapshot)
    plan = build_query_plan(company)
    limitations: list[str] = []
    all_hits: list[SearchHit] = []
    failed_categories: list[str] = []
    engine_warnings: list[str] = []
    ai_search_attempted = False
    ai_search_count = 0

    for spec in plan:
        run.refresh_from_db(fields=["cancellation_requested"])
        if run.cancellation_requested:
            return _cancel_run(run)
        try:
            hits = search_client.search(spec)
        except RuntimeError:
            failed_categories.append(spec.category)
            limitations.append(f"Recherche {spec.category} indisponible")
            SourceAttempt.objects.create(
                research_run=run,
                provider="searxng",
                query=spec.query,
                category=spec.category,
                status=SourceAttempt.Status.UNAVAILABLE,
                reason="Le moteur de recherche n’a pas répondu pour cette requête.",
            )
            continue
        for engine, reason in getattr(search_client, "last_warnings", ()):
            engine_warnings.append(f"{engine}: {reason}")
            limitations.append(f"Moteur {engine} indisponible : {reason}")
            SourceAttempt.objects.create(
                research_run=run,
                provider="searxng",
                query=spec.query,
                category=f"engine:{engine}"[:32],
                status=SourceAttempt.Status.UNAVAILABLE,
                reason=reason,
            )
        for hit in hits:
            score = rank_search_hit(hit.title, hit.snippet, hit.url, company)
            scored = SearchHit(**{**hit.__dict__, "discovery_score": score})
            all_hits.append(scored)
            SourceAttempt.objects.create(
                research_run=run,
                provider=hit.provider,
                query=hit.query,
                category=hit.category,
                url=hit.url,
                title=hit.title,
                snippet=hit.snippet[:2000],
                search_rank=hit.rank,
                relevance_score=score,
                status=SourceAttempt.Status.RETURNED,
            )

    searx_relevant_urls: set[str] = set()
    for hit in all_hits:
        if hit.discovery_score < 2:
            continue
        try:
            searx_relevant_urls.add(canonicalize_url(hit.url))
        except ValueError:
            continue
    searx_relevant_count = len(searx_relevant_urls)
    fallback_reasons: list[str] = []
    if failed_categories:
        fallback_reasons.append(f"requêtes indisponibles : {', '.join(failed_categories)}")
    if engine_warnings:
        fallback_reasons.append(f"moteurs bloqués ou indisponibles : {'; '.join(engine_warnings[:4])}")
    if searx_relevant_count < settings.ONBORA_GEMINI_FALLBACK_MIN_RESULTS:
        fallback_reasons.append(
            f"seulement {searx_relevant_count} résultat(s) SearXNG suffisamment pertinent(s)"
        )

    if ai_client and fallback_reasons:
        ai_search_attempted = True
        reason = " ; ".join(fallback_reasons)
        try:
            ai_hits = ai_client.search(company, reason)
        except GeminiServiceError as error:
            limitations.append(str(error))
            SourceAttempt.objects.create(
                research_run=run,
                provider="gemini",
                query=f"Complément Gemini pour {company.legal_name}",
                category="ai_fallback",
                status=SourceAttempt.Status.UNAVAILABLE,
                reason=str(error),
            )
        else:
            ai_search_count = len(ai_hits)
            for hit in ai_hits:
                score = rank_search_hit(hit.title, hit.snippet, hit.url, company)
                scored = SearchHit(**{**hit.__dict__, "discovery_score": score})
                all_hits.append(scored)
                SourceAttempt.objects.create(
                    research_run=run,
                    provider="gemini",
                    query=hit.query,
                    category=hit.category,
                    url=hit.url,
                    title=hit.title,
                    snippet=hit.snippet[:2000],
                    search_rank=hit.rank,
                    relevance_score=score,
                    status=SourceAttempt.Status.RETURNED,
                    reason="Source découverte avec Gemini et Google Search.",
                )

    deduplicated: dict[str, SearchHit] = {}
    for hit in all_hits:
        try:
            key = canonicalize_url(hit.url)
        except ValueError:
            continue
        current = deduplicated.get(key)
        if current is None or (hit.discovery_score, -hit.rank) > (current.discovery_score, -current.rank):
            deduplicated[key] = hit
    ranked = sorted(deduplicated.values(), key=lambda item: (-item.discovery_score, item.rank, item.url))
    candidates = [item for item in ranked if item.discovery_score >= 2]
    if not candidates:
        candidates = ranked[:3]
    selected: list[SearchHit] = []
    publisher_counts: defaultdict[str, int] = defaultdict(int)
    for item in candidates:
        publisher = _publisher(item.url)
        if publisher_counts[publisher] >= 2:
            continue
        selected.append(item)
        publisher_counts[publisher] += 1
        if len(selected) >= settings.ONBORA_ANALYSIS_LIMIT:
            break

    selected_urls = {canonicalize_url(item.url) for item in selected}
    for item in ranked:
        if canonicalize_url(item.url) not in selected_urls:
            SourceAttempt.objects.create(
                research_run=run,
                provider=item.provider,
                query=item.query,
                category=item.category,
                url=item.url,
                title=item.title,
                snippet=item.snippet[:2000],
                search_rank=item.rank,
                relevance_score=item.discovery_score,
                status=SourceAttempt.Status.FILTERED,
                reason="Résultat dédupliqué ou moins pertinent que les pages retenues.",
            )

    captured: list[RunEvidence] = []
    for position, hit in enumerate(selected, start=1):
        run.refresh_from_db(fields=["cancellation_requested"])
        if run.cancellation_requested:
            return _cancel_run(run)
        assessment = page_fetcher.analyze(hit, company)
        if assessment.error:
            limitations.append(f"Source inaccessible : {_publisher(hit.url) or hit.url}")
            SourceAttempt.objects.create(
                research_run=run,
                provider=hit.provider,
                query=hit.query,
                category=hit.category,
                url=hit.url,
                title=hit.title,
                search_rank=hit.rank,
                relevance_score=hit.discovery_score,
                status=SourceAttempt.Status.UNAVAILABLE,
                reason=assessment.error,
            )
            continue
        canonical_url = canonicalize_url(assessment.final_url)
        evidence, _created = EvidenceCapture.objects.get_or_create(
            canonical_url=canonical_url,
            content_hash=assessment.content_hash,
            defaults={
                "observed_url": assessment.final_url,
                "title": hit.title,
                "publisher": _publisher(assessment.final_url),
                "source_type": assessment.source_type,
                "relationship": assessment.relationship,
                "access_status": EvidenceCapture.AccessStatus.ACCESSIBLE,
            },
        )
        run_evidence, _linked = RunEvidence.objects.get_or_create(
            research_run=run,
            evidence=evidence,
            defaults={
                "position": position,
                "relevant_excerpt": assessment.excerpt,
                "relevance_score": assessment.score,
                "verdict": assessment.verdict,
                "reasons": list(assessment.reasons),
            },
        )
        captured.append(run_evidence)
        SourceAttempt.objects.create(
            research_run=run,
            provider=hit.provider,
            query=hit.query,
            category=hit.category,
            url=assessment.final_url,
            title=hit.title,
            search_rank=hit.rank,
            relevance_score=assessment.score,
            status=SourceAttempt.Status.ACCESSIBLE,
            reason=assessment.verdict,
        )

    usable_evidence = [item for item in captured if item.verdict in {"Pertinente", "À vérifier"}]
    if ai_client:
        try:
            ai_summary = ai_client.summarize(
                company,
                [
                    SummaryEvidence(
                        evidence_id=item.evidence_id,
                        title=item.evidence.title,
                        url=item.evidence.observed_url,
                        publisher=item.evidence.publisher,
                        source_type=item.evidence.source_type,
                        relationship=item.evidence.relationship,
                        verdict=item.verdict,
                        excerpt=item.relevant_excerpt,
                    )
                    for item in usable_evidence
                ],
            )
        except GeminiServiceError as error:
            ai_summary = {
                "status": "failed",
                "model": getattr(ai_client, "model", settings.ONBORA_GEMINI_MODEL),
                "message": f"{error} Les sources restent disponibles ci-dessous.",
            }
    else:
        ai_summary = {
            "status": "disabled",
            "message": "Gemini n’est pas activé ou aucune clé API n’est configurée.",
        }

    identity_status = _identity_status(captured)
    lead_qualification = build_lead_qualification(
        company,
        [
            LeadEvidence(
                evidence_id=item.evidence_id,
                title=item.evidence.title,
                publisher=item.evidence.publisher,
                relationship=item.evidence.relationship,
                excerpt=item.relevant_excerpt,
            )
            for item in usable_evidence
        ],
        identity_status,
    )
    sector_segmentation = build_sector_segmentation(
        company,
        [
            SectorEvidence(
                evidence_id=item.evidence_id,
                title=item.evidence.title,
                publisher=item.evidence.publisher,
                relationship=item.evidence.relationship,
                excerpt=item.relevant_excerpt,
            )
            for item in usable_evidence
        ],
        identity_status,
    )
    if lead_qualification.get("status") == "unavailable":
        limitations.append(lead_qualification.get("message", "Qualification commerciale indisponible."))
    verdict_counts: defaultdict[str, int] = defaultdict(int)
    for item in captured:
        verdict_counts[item.verdict] += 1
    summary = {
        "query_count": len(plan),
        "returned_count": len(all_hits),
        "unique_count": len(ranked),
        "analyzed_count": len(selected),
        "captured_count": len(captured),
        "verdict_counts": dict(verdict_counts),
        "ai_search_attempted": ai_search_attempted,
        "ai_search_source_count": ai_search_count,
        "sector_segmentation": sector_segmentation,
        "lead_qualification": lead_qualification,
    }
    with transaction.atomic():
        current = ResearchRun.objects.select_for_update().get(pk=run.pk)
        if current.cancellation_requested:
            previous_state = current.state
            current.state = ResearchRun.State.CANCELLED
            current.completed_at = timezone.now()
            current.lease_owner = ""
            current.lease_expires_at = None
            current.save()
            ResearchEvent.objects.create(
                research_run=current,
                event_type="research_cancelled",
                previous_state=previous_state,
                new_state=current.state,
            )
        else:
            previous_state = current.state
            current.state = ResearchRun.State.AWAITING_REVIEW
            current.coverage = ResearchRun.Coverage.PARTIAL if limitations else ResearchRun.Coverage.COMPLETE
            current.limitations = list(dict.fromkeys(limitations))
            current.identity_status = identity_status
            current.result_summary = summary
            current.ai_summary = ai_summary
            current.ai_model = getattr(ai_client, "model", "") if ai_client else ""
            current.completed_at = timezone.now()
            current.lease_owner = ""
            current.lease_expires_at = None
            current.save()
            ResearchEvent.objects.create(
                research_run=current,
                event_type="research_completed",
                previous_state=previous_state,
                new_state=current.state,
                details=summary,
            )
    return current


def _cancel_run(run: ResearchRun) -> ResearchRun:
    with transaction.atomic():
        current = ResearchRun.objects.select_for_update().get(pk=run.pk)
        if current.state == ResearchRun.State.CANCELLED:
            return current
        previous_state = current.state
        current.state = ResearchRun.State.CANCELLED
        current.completed_at = timezone.now()
        current.lease_owner = ""
        current.lease_expires_at = None
        current.save()
        ResearchEvent.objects.create(
            research_run=current,
            event_type="research_cancelled",
            previous_state=previous_state,
            new_state=current.state,
        )
    return current
