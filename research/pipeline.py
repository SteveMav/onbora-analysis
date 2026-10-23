"""Durable orchestration for one bounded company-research run."""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .gemini import GeminiResearchClient, GeminiServiceError, SummaryEvidence
from .openai_research import OpenAIResearchClient
from .lead_qualification import LeadEvidence, build_lead_qualification
from .models import EvidenceCapture, ResearchEvent, ResearchRun, RunEvidence, SourceAttempt
from .sector_segmentation import SectorEvidence, build_sector_segmentation
from .web_research import (
    PageFetcher,
    SearchHit,
    SearxngClient,
    build_lead_query_plan,
    build_profile_query_plan,
    build_query_plan,
    canonicalize_url,
    company_from_snapshot,
    company_website_domain,
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
        has_strong_attribute = any(value in joined for value in ("rccm", "numéro fiscal", "adresse arsp", "domaine du contact arsp"))
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


def _capture_hit(run, hit, position, company, page_fetcher, limitations):
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
        return None
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
    return run_evidence


def execute_research_run(
    run: ResearchRun,
    *,
    search_client: SearxngClient | None = None,
    page_fetcher: PageFetcher | None = None,
    ai_client: GeminiResearchClient | OpenAIResearchClient | None = None,
) -> ResearchRun:
    """Execute discovery, ranking, bounded fetching and evidence persistence."""
    search_client = search_client or SearxngClient()
    page_fetcher = page_fetcher or PageFetcher()
    ai_client = ai_client or OpenAIResearchClient.from_settings() or GeminiResearchClient.from_settings()
    company = company_from_snapshot(run.seed_snapshot)
    plan = build_query_plan(company)
    limitations: list[str] = []
    all_hits: list[SearchHit] = []
    failed_categories: list[str] = []
    engine_warnings: list[str] = []
    ai_search_attempted = False
    ai_search_count = 0
    ai_primary = isinstance(ai_client, OpenAIResearchClient)
    ai_discovery_used = False
    ai_summary_attempted = False

    def collect_ai_search(reason: str) -> list[SearchHit]:
        nonlocal ai_search_attempted, ai_search_count
        ai_search_attempted = True
        try:
            hits = ai_client.search(company, reason)
        except GeminiServiceError as error:
            limitations.append(str(error))
            SourceAttempt.objects.create(
                research_run=run,
                provider="openai" if ai_primary else "gemini",
                query=f"Recherche IA pour {company.legal_name}",
                category="ai_research" if ai_primary else "ai_fallback",
                status=SourceAttempt.Status.UNAVAILABLE,
                reason=str(error),
            )
            return []
        scored_hits = []
        for hit in hits:
            try:
                canonicalize_url(hit.url)
            except ValueError:
                continue
            score = rank_search_hit(hit.title, hit.snippet, hit.url, company)
            scored = SearchHit(**{**hit.__dict__, "discovery_score": score})
            scored_hits.append(scored)
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
                reason="Source découverte avec recherche web IA.",
            )
        ai_search_count = len(scored_hits)
        return scored_hits

    def collect_queries(specs) -> bool:
        for spec in specs:
            run.refresh_from_db(fields=["cancellation_requested"])
            if run.cancellation_requested:
                return False
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
        return True

    if ai_primary:
        run.refresh_from_db(fields=["cancellation_requested"])
        if run.cancellation_requested:
            return _cancel_run(run)
        ai_discovery_used = bool(collect_ai_search("Recherche initiale complète en un seul appel web"))
        if ai_discovery_used:
            plan = []
        else:
            limitations.append("Recherche OpenAI sans source exploitable ; recherche SearXNG de secours.")
    if not ai_discovery_used and not collect_queries(plan):
        return _cancel_run(run)

    # A structured registry contact can lead directly to the official site even
    # when search engines omit it. It must still pass public-URL and page checks.
    if domain := company_website_domain(company):
        url = f"https://{domain}/"
        hit = SearchHit(
            query="Domaine du contact ARSP", category="seed_website", rank=1,
            title=f"Site candidat de {company.legal_name}", url=url, snippet="",
            discovery_score=rank_search_hit(company.legal_name, "", url, company), provider="arsp",
        )
        all_hits.append(hit)
        SourceAttempt.objects.create(
            research_run=run, provider=hit.provider, query=hit.query, category=hit.category,
            url=url, title=hit.title, search_rank=1, relevance_score=hit.discovery_score,
            status=SourceAttempt.Status.RETURNED,
            reason="Domaine issu de l’adresse email du registre ARSP ; propriété à vérifier sur la page.",
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
    candidates = ranked if ai_discovery_used else [item for item in ranked if item.discovery_score >= 2]
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
    captured: list[RunEvidence] = []
    for position, hit in enumerate(selected, start=1):
        run.refresh_from_db(fields=["cancellation_requested"])
        if run.cancellation_requested:
            return _cancel_run(run)
        if evidence := _capture_hit(run, hit, position, company, page_fetcher, limitations):
            captured.append(evidence)

    rescue_count = 0
    if not any(item.verdict == "Pertinente" for item in captured):
        for hit in ranked:
            url = canonicalize_url(hit.url)
            publisher = _publisher(hit.url)
            if url in selected_urls or hit.discovery_score < 2 or publisher_counts[publisher] >= 2:
                continue
            if rescue_count >= settings.ONBORA_RESCUE_ANALYSIS_LIMIT:
                break
            run.refresh_from_db(fields=["cancellation_requested"])
            if run.cancellation_requested:
                return _cancel_run(run)
            selected.append(hit)
            selected_urls.add(url)
            publisher_counts[publisher] += 1
            rescue_count += 1
            if evidence := _capture_hit(run, hit, len(selected), company, page_fetcher, limitations):
                captured.append(evidence)
            if any(item.verdict == "Pertinente" for item in captured):
                break

    # The OpenAI-first path has already spent its single search request. The
    # legacy Gemini path can still discover sources after SearXNG fails.
    if ai_client and not ai_search_attempted and not any(item.verdict == "Pertinente" for item in captured):
        run.refresh_from_db(fields=["cancellation_requested"])
        if run.cancellation_requested:
            return _cancel_run(run)
        reasons = ["aucune page vérifiée comme pertinente après analyse SearXNG"]
        if failed_categories:
            reasons.append(f"requêtes indisponibles : {', '.join(failed_categories)}")
        if engine_warnings:
            reasons.append(f"moteurs bloqués ou indisponibles : {'; '.join(engine_warnings[:4])}")
        ai_hits = collect_ai_search(" ; ".join(reasons))
        if ai_hits:
            fallback_hits: dict[str, SearchHit] = {}
            for hit in ai_hits:
                url = canonicalize_url(hit.url)
                if url not in selected_urls and url not in fallback_hits:
                    fallback_hits[url] = hit
            publisher_counts = defaultdict(int)
            fallback_count = 0
            fallback_limit = (
                settings.ONBORA_OPENAI_MAX_SEARCH_SOURCES if isinstance(ai_client, OpenAIResearchClient)
                else settings.ONBORA_GEMINI_MAX_SEARCH_SOURCES
            )
            for hit in sorted(fallback_hits.values(), key=lambda item: (-item.discovery_score, item.rank, item.url)):
                publisher = _publisher(hit.url)
                if publisher_counts[publisher] >= 2 or fallback_count >= fallback_limit:
                    continue
                selected.append(hit)
                selected_urls.add(canonicalize_url(hit.url))
                publisher_counts[publisher] += 1
                fallback_count += 1
                run.refresh_from_db(fields=["cancellation_requested"])
                if run.cancellation_requested:
                    return _cancel_run(run)
                if evidence := _capture_hit(run, hit, len(selected), company, page_fetcher, limitations):
                    captured.append(evidence)
            for url, hit in fallback_hits.items():
                current = deduplicated.get(url)
                if current is None or hit.discovery_score > current.discovery_score:
                    deduplicated[url] = hit
            ranked = sorted(deduplicated.values(), key=lambda item: (-item.discovery_score, item.rank, item.url))

    profile_plan = []
    profile_count = 0
    if not ai_discovery_used and any(item.verdict == "Pertinente" for item in captured):
        profile_plan = build_profile_query_plan(company)
        if not collect_queries(profile_plan):
            return _cancel_run(run)
        profile_candidates: dict[str, SearchHit] = {}
        for hit in all_hits:
            if not hit.category.startswith("profile_"):
                continue
            url = canonicalize_url(hit.url)
            current = deduplicated.get(url)
            if current is None or hit.discovery_score > current.discovery_score:
                deduplicated[url] = hit
            if url not in selected_urls and (
                url not in profile_candidates or hit.discovery_score > profile_candidates[url].discovery_score
            ):
                profile_candidates[url] = hit
        profile_publishers: defaultdict[str, int] = defaultdict(int)
        for hit in sorted(profile_candidates.values(), key=lambda item: (-item.discovery_score, item.rank, item.url)):
            publisher = _publisher(hit.url)
            if hit.discovery_score < 2 or profile_publishers[publisher] >= 2:
                continue
            if profile_count >= settings.ONBORA_PROFILE_ANALYSIS_LIMIT:
                break
            run.refresh_from_db(fields=["cancellation_requested"])
            if run.cancellation_requested:
                return _cancel_run(run)
            selected.append(hit)
            selected_urls.add(canonicalize_url(hit.url))
            profile_publishers[publisher] += 1
            profile_count += 1
            if evidence := _capture_hit(run, hit, len(selected), company, page_fetcher, limitations):
                captured.append(evidence)
        ranked = sorted(deduplicated.values(), key=lambda item: (-item.discovery_score, item.rank, item.url))

    lead_plan = []
    if not ai_discovery_used and settings.ONBORA_LEAD_QUALIFICATION_ENABLED and any(item.verdict == "Pertinente" for item in captured):
        lead_plan = build_lead_query_plan(company)
        if not collect_queries(lead_plan):
            return _cancel_run(run)
        lead_candidates: dict[str, SearchHit] = {}
        for hit in all_hits:
            if not hit.category.startswith("lead_"):
                continue
            url = canonicalize_url(hit.url)
            current = deduplicated.get(url)
            if current is None or hit.discovery_score > current.discovery_score:
                deduplicated[url] = hit
            if url not in selected_urls and (
                url not in lead_candidates or hit.discovery_score > lead_candidates[url].discovery_score
            ):
                lead_candidates[url] = hit
        lead_publishers: defaultdict[str, int] = defaultdict(int)
        lead_count = 0
        for hit in sorted(lead_candidates.values(), key=lambda item: (-item.discovery_score, item.rank, item.url)):
            publisher = _publisher(hit.url)
            if hit.discovery_score < 2 or lead_publishers[publisher] >= 2:
                continue
            if lead_count >= settings.ONBORA_LEAD_ANALYSIS_LIMIT:
                break
            run.refresh_from_db(fields=["cancellation_requested"])
            if run.cancellation_requested:
                return _cancel_run(run)
            selected.append(hit)
            selected_urls.add(canonicalize_url(hit.url))
            lead_publishers[publisher] += 1
            lead_count += 1
            if evidence := _capture_hit(run, hit, len(selected), company, page_fetcher, limitations):
                captured.append(evidence)
        ranked = sorted(deduplicated.values(), key=lambda item: (-item.discovery_score, item.rank, item.url))

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
                reason="Résultat moins prioritaire que les pages analysées.",
            )

    usable_evidence = [item for item in captured if item.verdict in {"Pertinente", "À vérifier"}]
    usable_evidence.sort(key=lambda item: (
        item.verdict == "Pertinente", item.evidence.relationship == "first_party",
        item.relevance_score, len(item.relevant_excerpt),
    ), reverse=True)
    if not usable_evidence:
        ai_summary = {
            "status": "not_generated",
            "message": "Aucune page analysée ne relie suffisamment cette source à l’entreprise. Aucun résumé n’a été généré.",
        }
    elif ai_client:
        ai_summary_attempted = True
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
                "model": getattr(ai_client, "model", ""),
                "message": f"{error} Les sources restent disponibles ci-dessous.",
            }
    else:
        ai_summary = {
            "status": "disabled",
            "message": "Aucun fournisseur IA n’est activé ou aucune clé API n’est configurée.",
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
        "query_count": len(plan) + len(profile_plan) + len(lead_plan) + int(ai_search_attempted),
        "returned_count": len(all_hits),
        "unique_count": len(ranked),
        "analyzed_count": len(selected),
        "rescue_analyzed_count": rescue_count,
        "captured_count": len(captured),
        "usable_count": len(usable_evidence),
        "analysis_failure_count": len(selected) - len(captured),
        "verdict_counts": dict(verdict_counts),
        "ai_search_attempted": ai_search_attempted,
        "ai_search_source_count": ai_search_count,
        "discovery_provider": "openai" if ai_discovery_used else "searxng",
        "ai_search_request_count": int(ai_search_attempted),
        "ai_summary_request_count": int(ai_summary_attempted),
        "lead_query_count": len(lead_plan),
        "profile_query_count": len(profile_plan),
        "profile_analyzed_count": profile_count,
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
