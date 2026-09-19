from __future__ import annotations

import random

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import HumanBenchmarkCaseForm
from .lead_qualification import (
    LeadEvidence,
    LeadQualificationError,
    active_rdc_journey_ids,
    available_rdc_offer_ids,
    build_lead_qualification,
)
from .models import (
    AuditEvent,
    ArspImport,
    ArspRecord,
    HumanBenchmark,
    HumanBenchmarkCase,
    ResearchRun,
    SourceAttempt,
)
from .permissions import can_view_run, has_role
from .sector_segmentation import SectorEvidence, build_sector_segmentation
from .services import create_or_get_active_run
from .web_research import canonicalize_url, company_from_snapshot


def _evidence_sources(evidence_ids: list, evidence_by_id: dict[int, object]) -> list[dict]:
    sources = []
    for evidence_id in evidence_ids:
        link = evidence_by_id.get(evidence_id)
        if link:
            sources.append({
                "evidence_id": evidence_id,
                "title": link.evidence.title or link.evidence.publisher or link.evidence.observed_url,
                "url": link.evidence.observed_url,
                "publisher": link.evidence.publisher,
            })
    return sources


def _statement_with_sources(statement: dict, evidence_by_id: dict[int, object]) -> dict:
    return {
        "text": statement.get("text", ""),
        "sources": _evidence_sources(statement.get("evidence_ids", []), evidence_by_id),
    }


def _ai_summary_view(summary: dict, evidence_links: list) -> dict:
    if summary.get("status") != "complete":
        return summary
    evidence_by_id = {link.evidence_id: link for link in evidence_links}
    return {
        **summary,
        "overview": _statement_with_sources(summary.get("overview", {}), evidence_by_id),
        "key_facts": [
            _statement_with_sources(item, evidence_by_id) for item in summary.get("key_facts", [])
        ],
        "contradictions": [
            _statement_with_sources(item, evidence_by_id) for item in summary.get("contradictions", [])
        ],
    }


def _lead_qualification_view(qualification: dict, evidence_links: list) -> dict:
    if qualification.get("status") != "complete":
        return qualification
    try:
        rdc_offer_ids = available_rdc_offer_ids()
        rdc_journey_ids = active_rdc_journey_ids()
    except LeadQualificationError as error:
        return {"status": "unavailable", "message": str(error)}
    evidence_by_id = {link.evidence_id: link for link in evidence_links}
    journeys = []
    for journey in qualification.get("journeys", []):
        if journey.get("journey_id") not in rdc_journey_ids:
            continue
        signals = [
            {
                **signal,
                "sources": _evidence_sources(signal.get("evidence_ids", []), evidence_by_id),
            }
            for signal in journey.get("signals", [])
        ]
        journeys.append({
            **journey,
            "signals": signals,
            "sources": _evidence_sources(journey.get("evidence_ids", []), evidence_by_id),
            "offers": [
                {**offer, "rdc_availability": "available", "market": "RDC"}
                for offer in journey.get("offers", [])
                if offer.get("service_id") in rdc_offer_ids
            ],
        })
    verdict_order = {"prioritaire": 0, "a_explorer": 1, "non_qualifiable": 2}
    journeys.sort(key=lambda item: (verdict_order.get(item.get("verdict"), 9), item.get("title", "")))
    return {**qualification, "market": "RDC", "journeys": journeys}


def _sector_segmentation_view(segmentation: dict, evidence_links: list) -> dict:
    if segmentation.get("status") != "complete":
        return segmentation
    evidence_by_id = {link.evidence_id: link for link in evidence_links}
    primary = segmentation.get("primary") or {}
    alternatives = [
        {
            **item,
            "sources": _evidence_sources(item.get("evidence_ids", []), evidence_by_id),
        }
        for item in segmentation.get("alternatives", [])
    ]
    return {
        **segmentation,
        "primary": {
            **primary,
            "sources": _evidence_sources(primary.get("evidence_ids", []), evidence_by_id),
        },
        "alternatives": alternatives,
    }


@login_required
@require_GET
def dashboard(request: HttpRequest) -> HttpResponse:
    if not has_role(request.user, "kam", "reviewer", "operator", "admin"):
        return HttpResponseForbidden("Ce compte n’a pas de rôle Onbora.")
    query = request.GET.get("q", "").strip()[:200]
    latest_import = ArspImport.objects.order_by("-imported_at").first()
    records = ArspRecord.objects.none()
    if latest_import:
        records = ArspRecord.objects.filter(arsp_import=latest_import)
        if query:
            records = records.filter(Q(legal_name__icontains=query) | Q(dossier_number__icontains=query))
        records = records.order_by("legal_name")
    page_obj = Paginator(records, 100).get_page(request.GET.get("page"))
    recent_runs = (
        ResearchRun.objects.select_related("source_record")
        .filter(requested_by=request.user)
        .order_by("-created_at")[:10]
    )
    return render(request, "research/dashboard.html", {
        "latest_import": latest_import,
        "records": page_obj.object_list,
        "page_obj": page_obj,
        "query": query,
        "recent_runs": recent_runs,
    })


@login_required
@require_POST
def create_run(request: HttpRequest) -> HttpResponse:
    if not has_role(request.user, "kam", "operator", "admin"):
        raise Http404
    try:
        record_id = int(request.POST["record_id"])
    except (KeyError, TypeError, ValueError):
        return redirect("dashboard")
    record = get_object_or_404(ArspRecord.objects.select_related("arsp_import"), pk=record_id)
    run, _created = create_or_get_active_run(record=record, requested_by=request.user)
    return redirect("web-run-detail", run_id=run.pk)


@login_required
@require_GET
def run_detail(request: HttpRequest, run_id: int) -> HttpResponse:
    run = get_object_or_404(
        ResearchRun.objects.select_related("source_record", "requested_by"),
        pk=run_id,
    )
    if not can_view_run(request.user, run):
        raise Http404
    evidence_links = list(run.run_evidence.select_related("evidence"))
    relevant = [link for link in evidence_links if link.verdict in {"Pertinente", "À vérifier"}]
    rejected = [link for link in evidence_links if link.verdict == "Hors sujet probable"]
    attempts = list(run.source_attempts.order_by("-created_at"))
    evaluations = {link.evidence.canonical_url: link for link in evidence_links}
    resolved_urls: dict[tuple[str, str, str], str] = {}
    for attempt in attempts:
        if attempt.status == attempt.Status.ACCESSIBLE and attempt.url:
            resolved_urls[(attempt.provider, attempt.query, attempt.title)] = attempt.url
    discovered: dict[str, dict] = {}
    for attempt in attempts:
        if attempt.status != attempt.Status.RETURNED or not attempt.url:
            continue
        display_url = resolved_urls.get((attempt.provider, attempt.query, attempt.title), attempt.url)
        try:
            canonical_url = canonicalize_url(display_url)
        except ValueError:
            canonical_url = display_url
        current = discovered.get(canonical_url)
        if current is None or attempt.relevance_score > current["attempt"].relevance_score:
            discovered[canonical_url] = {
                "attempt": attempt,
                "evaluation": evaluations.get(canonical_url),
                "url": display_url,
            }
    discovered_sources = sorted(
        discovered.values(),
        key=lambda item: (-item["attempt"].relevance_score, item["attempt"].search_rank, item["attempt"].title),
    )
    lead_qualification = run.result_summary.get("lead_qualification", {})
    if not lead_qualification and run.state not in {ResearchRun.State.QUEUED, ResearchRun.State.RESEARCHING}:
        lead_qualification = build_lead_qualification(
            company_from_snapshot(run.seed_snapshot),
            [
                LeadEvidence(
                    evidence_id=link.evidence_id,
                    title=link.evidence.title,
                    publisher=link.evidence.publisher,
                    relationship=link.evidence.relationship,
                    excerpt=link.relevant_excerpt,
                )
                for link in relevant
            ],
            run.identity_status,
        )
    sector_segmentation = run.result_summary.get("sector_segmentation", {})
    if not sector_segmentation and run.state not in {ResearchRun.State.QUEUED, ResearchRun.State.RESEARCHING}:
        sector_segmentation = build_sector_segmentation(
            company_from_snapshot(run.seed_snapshot),
            [
                SectorEvidence(
                    evidence_id=link.evidence_id,
                    title=link.evidence.title,
                    publisher=link.evidence.publisher,
                    relationship=link.evidence.relationship,
                    excerpt=link.relevant_excerpt,
                )
                for link in relevant
            ],
            run.identity_status,
        )
    return render(request, "research/run_detail.html", {
        "run": run,
        "seed": run.seed_snapshot.get("input_snapshot", {}),
        "relevant_evidence": relevant,
        "rejected_evidence": rejected,
        "discovered_sources": discovered_sources,
        "attempts": attempts,
        "ai_summary": _ai_summary_view(run.ai_summary, evidence_links),
        "sector_segmentation": _sector_segmentation_view(sector_segmentation, evidence_links),
        "lead_qualification": _lead_qualification_view(lead_qualification, evidence_links),
        "is_active": run.state in {ResearchRun.State.QUEUED, ResearchRun.State.RESEARCHING},
    })


def _require_benchmark_role(user) -> None:
    if not has_role(user, "reviewer", "operator", "admin"):
        raise Http404


def _benchmark_context(
    benchmark: HumanBenchmark,
    *,
    bound_case_id: int | None = None,
    bound_form: HumanBenchmarkCaseForm | None = None,
) -> dict:
    cases = list(
        benchmark.cases.select_related("source_record", "research_run", "reviewed_by")
        .prefetch_related(
            "research_run__run_evidence__evidence",
            Prefetch(
                "research_run__source_attempts",
                queryset=SourceAttempt.objects.order_by("-relevance_score", "search_rank", "id"),
            ),
        )
    )
    for case in cases:
        case.evaluation_form = (
            bound_form if bound_case_id == case.pk and bound_form is not None
            else HumanBenchmarkCaseForm(instance=case, prefix=f"case-{case.pk}")
        )
        case.evidence_links = []
        case.discovered_sources = []
        if case.research_run_id:
            case.evidence_links = [
                link
                for link in case.research_run.run_evidence.all()
                if link.verdict in {"Pertinente", "À vérifier"}
            ]
            seen_urls: set[str] = set()
            for attempt in case.research_run.source_attempts.all():
                if attempt.status != attempt.Status.RETURNED or not attempt.url:
                    continue
                try:
                    key = canonicalize_url(attempt.url)
                except ValueError:
                    key = attempt.url
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                case.discovered_sources.append(attempt)
                if len(case.discovered_sources) >= 8:
                    break

    completed = [case for case in cases if case.review_status == HumanBenchmarkCase.ReviewStatus.COMPLETED]
    human_value = [
        case for case in completed
        if case.source_potential in {HumanBenchmarkCase.SourcePotential.LIMITED, HumanBenchmarkCase.SourcePotential.USEFUL}
    ]
    system_value = [
        case for case in completed
        if case.system_verdict in {HumanBenchmarkCase.SystemVerdict.USEFUL, HumanBenchmarkCase.SystemVerdict.PARTIAL}
    ]
    metrics = {
        "total": len(cases),
        "completed": len(completed),
        "human_value": len(human_value),
        "system_value": len(system_value),
        "missed": sum(bool(case.missed_information.strip()) for case in completed),
        "identity_errors": sum(
            case.identity_check == HumanBenchmarkCase.IdentityCheck.INCORRECT for case in completed
        ),
        "human_value_pct": round(len(human_value) * 100 / len(completed)) if completed else 0,
        "system_value_pct": round(len(system_value) * 100 / len(completed)) if completed else 0,
    }
    return {"benchmark": benchmark, "cases": cases, "metrics": metrics}


@login_required
@require_GET
def benchmark_list(request: HttpRequest) -> HttpResponse:
    _require_benchmark_role(request.user)
    benchmarks = HumanBenchmark.objects.select_related("created_by").prefetch_related("cases").all()
    completed_runs = ResearchRun.objects.filter(
        state__in=[ResearchRun.State.AWAITING_REVIEW, ResearchRun.State.REVIEWED]
    ).values("source_record_id").distinct().count()
    return render(request, "research/benchmark_list.html", {
        "benchmarks": benchmarks,
        "latest_import": ArspImport.objects.order_by("-imported_at").first(),
        "completed_run_count": completed_runs,
    })


@login_required
@require_POST
def benchmark_create(request: HttpRequest) -> HttpResponse:
    _require_benchmark_role(request.user)
    latest_import = ArspImport.objects.order_by("-imported_at").first()
    if latest_import is None:
        messages.error(request, "Importe d’abord la base ARSP.")
        return redirect("benchmark-list")

    mode = request.POST.get("selection_mode", "random")
    name = request.POST.get("name", "").strip()[:255] or f"Benchmark du {timezone.localdate():%d/%m/%Y}"
    selected: list[tuple[ArspRecord, ResearchRun | None]] = []
    if mode == "recent":
        seen_records: set[int] = set()
        runs = ResearchRun.objects.select_related("source_record").filter(
            state__in=[ResearchRun.State.AWAITING_REVIEW, ResearchRun.State.REVIEWED]
        ).order_by("-completed_at", "-id")
        for run in runs:
            if run.source_record_id in seen_records:
                continue
            seen_records.add(run.source_record_id)
            selected.append((run.source_record, run))
            if len(selected) == 10:
                break
        if len(selected) < 10:
            messages.error(request, "Il faut au moins 10 entreprises déjà recherchées pour utiliser ce mode.")
            return redirect("benchmark-list")
    elif mode == "random":
        record_ids = list(
            ArspRecord.objects.filter(arsp_import=latest_import).values_list("id", flat=True)
        )
        if len(record_ids) < 10:
            messages.error(request, "La base ARSP doit contenir au moins 10 entreprises.")
            return redirect("benchmark-list")
        sampled_ids = random.SystemRandom().sample(record_ids, 10)
        records_by_id = ArspRecord.objects.in_bulk(sampled_ids)
        selected = [(records_by_id[record_id], None) for record_id in sampled_ids]
    else:
        messages.error(request, "Mode de sélection inconnu.")
        return redirect("benchmark-list")

    with transaction.atomic():
        benchmark = HumanBenchmark.objects.create(name=name, created_by=request.user)
        for position, (record, existing_run) in enumerate(selected, start=1):
            run = existing_run
            if run is None:
                run = (
                    ResearchRun.objects.filter(
                        source_record=record,
                        state__in=[ResearchRun.State.AWAITING_REVIEW, ResearchRun.State.REVIEWED],
                    )
                    .order_by("-completed_at", "-id")
                    .first()
                )
            if run is None:
                run, _created = create_or_get_active_run(record=record, requested_by=request.user)
            HumanBenchmarkCase.objects.create(
                benchmark=benchmark,
                source_record=record,
                research_run=run,
                position=position,
            )
        AuditEvent.objects.create(
            actor=request.user,
            action="human_benchmark_created",
            resource_type="human_benchmark",
            resource_id=str(benchmark.pk),
            details={"selection_mode": mode, "case_count": 10},
        )
    messages.success(request, "Le benchmark de 10 entreprises est prêt.")
    return redirect("benchmark-detail", benchmark_id=benchmark.pk)


@login_required
@require_GET
def benchmark_detail(request: HttpRequest, benchmark_id: int) -> HttpResponse:
    _require_benchmark_role(request.user)
    benchmark = get_object_or_404(HumanBenchmark.objects.select_related("created_by"), pk=benchmark_id)
    return render(request, "research/benchmark_detail.html", _benchmark_context(benchmark))


@login_required
@require_POST
def benchmark_case_update(request: HttpRequest, benchmark_id: int, case_id: int) -> HttpResponse:
    _require_benchmark_role(request.user)
    benchmark = get_object_or_404(HumanBenchmark.objects.select_related("created_by"), pk=benchmark_id)
    case = get_object_or_404(HumanBenchmarkCase, pk=case_id, benchmark=benchmark)
    form = HumanBenchmarkCaseForm(request.POST, instance=case, prefix=f"case-{case.pk}")
    if not form.is_valid():
        context = _benchmark_context(benchmark, bound_case_id=case.pk, bound_form=form)
        return render(request, "research/benchmark_detail.html", context, status=400)

    with transaction.atomic():
        case = form.save(commit=False)
        is_complete = (
            case.source_potential != HumanBenchmarkCase.SourcePotential.UNKNOWN
            and case.system_verdict != HumanBenchmarkCase.SystemVerdict.NOT_REVIEWED
            and case.identity_check != HumanBenchmarkCase.IdentityCheck.NOT_REVIEWED
        )
        case.review_status = (
            HumanBenchmarkCase.ReviewStatus.COMPLETED
            if is_complete else HumanBenchmarkCase.ReviewStatus.PENDING
        )
        case.reviewed_by = request.user if is_complete else None
        case.reviewed_at = timezone.now() if is_complete else None
        case.save()

        remaining = benchmark.cases.exclude(review_status=HumanBenchmarkCase.ReviewStatus.COMPLETED).exists()
        benchmark.status = (
            HumanBenchmark.Status.IN_PROGRESS if remaining else HumanBenchmark.Status.COMPLETED
        )
        benchmark.completed_at = None if remaining else timezone.now()
        benchmark.save(update_fields=["status", "completed_at"])
        AuditEvent.objects.create(
            actor=request.user,
            action="human_benchmark_case_updated",
            resource_type="human_benchmark_case",
            resource_id=str(case.pk),
            details={"benchmark_id": benchmark.pk, "review_status": case.review_status},
        )
    messages.success(request, f"Évaluation {case.position}/10 enregistrée.")
    return redirect(f"{redirect('benchmark-detail', benchmark_id=benchmark.pk).url}#case-{case.pk}")
