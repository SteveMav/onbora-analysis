"""Compact batch selection and reports, using the existing research pipeline."""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST

from .models import ArspImport, ArspRecord, ResearchBatch, ResearchBatchItem, ResearchRun
from .permissions import has_role
from .services import create_or_get_active_run
from .web_views import _ai_summary_view, _lead_qualification_view

ACTIVE_STATES = {ResearchRun.State.QUEUED, ResearchRun.State.RESEARCHING}


@login_required
@require_GET
def selection(request):
    if not has_role(request.user, "kam", "operator", "admin"):
        raise Http404
    latest_import = ArspImport.objects.first()
    query = request.GET.get("q", "").strip()[:200]
    records = ArspRecord.objects.none()
    if latest_import:
        records = latest_import.records.all()
        if query:
            records = records.filter(Q(legal_name__icontains=query) | Q(dossier_number__icontains=query))
    page = Paginator(records.order_by("legal_name", "pk"), 25).get_page(request.GET.get("page"))
    context = {
        "latest_import": latest_import, "query": query, "page_obj": page,
        "submission_id": str(uuid.uuid4()),
        "recent_batches": ResearchBatch.objects.filter(requested_by=request.user).annotate(
            company_count=Count("items")
        )[:10],
    }
    if request.GET.get("fragment") == "1":
        return JsonResponse({"html": render_to_string("research/multi_company_list.html", context, request=request)})
    return render(request, "research/multi_search.html", context)


@login_required
@require_POST
def create(request):
    if not has_role(request.user, "kam", "operator", "admin"):
        raise Http404
    try:
        submission_id = uuid.UUID(request.POST.get("submission_id", ""))
        record_ids = [int(value) for value in request.POST.getlist("record_ids")]
    except (ValueError, TypeError):
        messages.error(request, "La sélection est invalide. Sélectionne à nouveau tes entreprises.")
        return redirect("multi-search")
    existing = ResearchBatch.objects.filter(submission_id=submission_id).first()
    if existing:
        if existing.requested_by_id != request.user.pk:
            raise Http404
        return redirect("multi-search-detail", batch_id=existing.pk)
    if not 1 <= len(record_ids) <= 5 or len(set(record_ids)) != len(record_ids):
        messages.error(request, "Sélectionne entre 1 et 5 entreprises différentes.")
        return redirect("multi-search")
    latest_import = ArspImport.objects.first()
    records = {record.pk: record for record in ArspRecord.objects.select_related("arsp_import").filter(
        arsp_import=latest_import, pk__in=record_ids,
    )}
    if len(records) != len(record_ids):
        messages.error(request, "Une entreprise n’est plus dans l’import actif. Actualise ta sélection.")
        return redirect("multi-search")
    with transaction.atomic():
        batch, created = ResearchBatch.objects.get_or_create(
            submission_id=submission_id, defaults={"requested_by": request.user},
        )
        if batch.requested_by_id != request.user.pk:
            raise Http404
        if created:
            for position, record_id in enumerate(record_ids, 1):
                run, _ = create_or_get_active_run(record=records[record_id], requested_by=request.user)
                ResearchBatchItem.objects.create(batch=batch, research_run=run, position=position)
    return redirect("multi-search-detail", batch_id=batch.pk)


def _report_card(item):
    run = item.research_run
    links = [link for link in run.run_evidence.all() if link.verdict in {"Pertinente", "À vérifier"}]
    summary = _ai_summary_view(run.ai_summary, links)
    # An uncited statement must not become a fact merely because it is in a saved JSON.
    if summary.get("status") == "complete":
        overview = summary.get("overview", {})
        if not overview.get("text") or not overview.get("sources"):
            summary = {"status": "unavailable", "message": "Le résumé ne dispose pas de sources vérifiables."}
        else:
            summary["key_facts"] = [fact for fact in summary.get("key_facts", []) if fact.get("sources")]
            summary["contradictions"] = [fact for fact in summary.get("contradictions", []) if fact.get("sources")]
    qualification = _lead_qualification_view(run.result_summary.get("lead_qualification", {}), links)
    opportunities = [
        journey for journey in qualification.get("journeys", [])
        if journey.get("verdict") in {"prioritaire", "a_explorer"} and journey.get("offers")
        and (journey.get("sources") or journey.get("sector_fit"))
    ]
    seed = run.seed_snapshot.get("input_snapshot", {})
    return {
        "position": item.position, "run": run, "name": run.source_record.display_legal_name,
        "seed": seed, "active": run.state in ACTIVE_STATES,
        "successful": run.state in {ResearchRun.State.AWAITING_REVIEW, ResearchRun.State.REVIEWED},
        "summary": summary, "links": links, "opportunities": opportunities,
        "qualification": qualification,
    }


def _report_text(cards):
    sections = []
    for card in cards:
        run, summary = card["run"], card["summary"]
        lines = [f'{card["position"]}. {card["name"]}']
        if card["active"]:
            lines.append(run.get_state_display())
        elif not card["successful"]:
            lines.append(run.get_state_display())
            lines.extend(run.limitations)
        elif summary.get("status") == "complete":
            statements = [summary["overview"], *summary.get("key_facts", []), *summary.get("contradictions", [])]
            for statement in statements:
                lines.append(statement["text"])
                lines.extend(f'Source : {source["url"]}' for source in statement["sources"])
            lines.extend(f'À vérifier : {gap}' for gap in summary.get("gaps", []))
        else:
            lines.append("Résumé IA indisponible. " + summary.get("message", ""))
            lines.extend(f'Extrait collecté : {link.relevant_excerpt}\nSource : {link.evidence.observed_url}' for link in card["links"][:2])
        for journey in card["opportunities"] if card["successful"] else []:
            lines.append("Offres à explorer : " + ", ".join(offer["name"] for offer in journey["offers"]))
            lines.append(journey.get("reason", ""))
            if not journey["sources"]:
                lines.append("Hypothèse fondée sur l’activité déclarée dans l’ARSP.")
            lines.extend(f'Source : {source["url"]}' for source in journey["sources"])
            lines.append("À demander : " + journey.get("next_question", ""))
        if card["successful"] and card["links"]:
            lines.append("Sources retenues :")
            lines.extend(link.evidence.observed_url for link in card["links"])
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


@login_required
@require_GET
def detail(request, batch_id):
    batch = get_object_or_404(ResearchBatch, pk=batch_id)
    if not (has_role(request.user, "operator", "reviewer", "admin") or
            (has_role(request.user, "kam") and batch.requested_by_id == request.user.pk)):
        raise Http404
    items = batch.items.select_related("research_run__source_record").prefetch_related(
        "research_run__run_evidence__evidence",
    )
    cards = [_report_card(item) for item in items]
    finished = sum(not card["active"] for card in cards)
    successful = sum(card["successful"] for card in cards)
    context = {
        "batch": batch, "cards": cards, "total": len(cards), "finished": finished,
        "successful": successful, "failed": finished - successful,
        "active": finished < len(cards), "report_text": _report_text(cards),
    }
    if request.GET.get("fragment") == "1":
        return JsonResponse({
            "html": render_to_string("research/multi_results.html", context, request=request),
            "active": context["active"],
        })
    return render(request, "research/multi_detail.html", context)
