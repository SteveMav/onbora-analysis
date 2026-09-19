from __future__ import annotations

import json

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .models import ArspRecord, ResearchRun
from .permissions import can_view_run, has_role
from .services import create_or_get_active_run, request_cancellation
from .web_research import canonicalize_url


def _json_body(request: HttpRequest) -> dict:
    try:
        value = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("validation_failed")
    if not isinstance(value, dict):
        raise ValueError("validation_failed")
    return value


def _not_found_or_forbidden() -> JsonResponse:
    return JsonResponse({"error": "not_found_or_forbidden"}, status=404)


def _run_payload(run: ResearchRun) -> dict:
    payload = {
        "run_id": run.pk,
        "state": run.state,
        "coverage": run.coverage,
        "limitations": run.limitations,
        "cancellation_requested": run.cancellation_requested,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "identity": {"status": run.identity_status or None},
        "summary": run.result_summary,
        "ai_summary": run.ai_summary,
        "ai_model": run.ai_model or None,
    }
    payload["evidence"] = [
        {
            "evidence_id": link.evidence_id,
            "url": link.evidence.observed_url,
            "title": link.evidence.title,
            "publisher": link.evidence.publisher,
            "source_type": link.evidence.source_type,
            "relationship": link.evidence.relationship,
            "access_status": link.evidence.access_status,
            "relevance_score": link.relevance_score,
            "verdict": link.verdict,
            "reasons": link.reasons,
            "relevant_excerpt": link.relevant_excerpt,
            "collected_at": link.evidence.collected_at.isoformat(),
        }
        for link in run.run_evidence.select_related("evidence").all()
    ]
    sources = []
    seen_urls: set[str] = set()
    for attempt in run.source_attempts.filter(status="returned").order_by("-relevance_score", "search_rank", "id"):
        try:
            canonical_url = canonicalize_url(attempt.url)
        except ValueError:
            canonical_url = attempt.url
        if not canonical_url or canonical_url in seen_urls:
            continue
        seen_urls.add(canonical_url)
        sources.append({
            "url": attempt.url,
            "title": attempt.title,
            "snippet": attempt.snippet,
            "category": attempt.category,
            "query": attempt.query,
            "provider": attempt.provider,
            "discovery_score": attempt.relevance_score,
        })
    payload["sources"] = sources
    payload["search_diagnostics"] = [
        {
            "category": attempt.category,
            "query": attempt.query,
            "provider": attempt.provider,
            "reason": attempt.reason,
        }
        for attempt in run.source_attempts.filter(status="unavailable", url="").order_by("created_at", "id")
    ]
    return payload


@require_POST
def create_research_run(request: HttpRequest) -> JsonResponse:
    if not has_role(request.user, "kam", "operator", "admin"):
        return _not_found_or_forbidden()
    try:
        body = _json_body(request)
        record_id = int(body["source_record_id"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "validation_failed", "field": "source_record_id"}, status=400)

    try:
        record = ArspRecord.objects.select_related("arsp_import").get(pk=record_id)
    except ArspRecord.DoesNotExist:
        return _not_found_or_forbidden()

    run, created = create_or_get_active_run(record=record, requested_by=request.user)
    return JsonResponse(_run_payload(run), status=201 if created else 200)


@require_GET
def get_research_run(request: HttpRequest, run_id: int) -> JsonResponse:
    try:
        run = ResearchRun.objects.get(pk=run_id)
    except ResearchRun.DoesNotExist:
        return _not_found_or_forbidden()
    if not can_view_run(request.user, run):
        return _not_found_or_forbidden()
    return JsonResponse(_run_payload(run))


@require_POST
def cancel_research_run(request: HttpRequest, run_id: int) -> JsonResponse:
    if not has_role(request.user, "operator", "admin"):
        return _not_found_or_forbidden()
    try:
        run = ResearchRun.objects.get(pk=run_id)
    except ResearchRun.DoesNotExist:
        return _not_found_or_forbidden()
    try:
        run = request_cancellation(run=run, actor=request.user)
    except ValueError:
        return JsonResponse({"error": "invalid_state"}, status=409)
    return JsonResponse(_run_payload(run), status=202)
