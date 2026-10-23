from __future__ import annotations

import csv
import json
import re
import uuid

from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import serpapi
from .models import ArspImport, ArspRecord, SerpApiSearch
from .permissions import has_role
from .text_utils import clean_excel_text


def _active_records():
    return ArspRecord.objects.filter(arsp_import=ArspImport.objects.first())


def _company_input(record):
    return {
        "id": record.pk, "name": record.display_legal_name,
        "province": clean_excel_text(record.raw_data.get("Province", "")),
        "dossier": clean_excel_text(record.dossier_number),
    }


def _company_query(record):
    company = _company_input(record)
    return " ".join(value for value in (company["name"], company["province"], "RDC") if value)[:500]


class SearchForm(forms.Form):
    submission_id = forms.UUIDField(widget=forms.HiddenInput)
    company_source = forms.ChoiceField(
        label="Entreprise à rechercher", required=False,
        choices=(("manual", "Saisie libre"), ("arsp", "Choisir dans la base ARSP")),
        widget=forms.RadioSelect(attrs={"form": "serp-search-form"}),
    )
    record_id = forms.ModelChoiceField(queryset=ArspRecord.objects.none(), required=False, widget=forms.HiddenInput)
    scenario = forms.ChoiceField(label="Scénario", choices=serpapi.SCENARIOS)
    engine = forms.ChoiceField(label="Moteur", choices=serpapi.SEARCH_OPTIONS)
    query = forms.CharField(label="Requête envoyée à SerpApi", min_length=2, max_length=500,
                           widget=forms.Textarea(attrs={"rows": 3}))
    language = forms.ChoiceField(label="Langue", choices=(("fr", "Français"), ("en", "Anglais")))
    country = forms.ChoiceField(label="Pays Google (Web / News)", choices=(("cd", "RDC"), ("fr", "France"), ("us", "États-Unis")))
    coordinates = forms.CharField(label="Centre de carte (Maps, facultatif)", required=False, max_length=100,
                                  help_text="Format : @latitude,longitude,14z. Sinon, précise la ville dans la requête.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["record_id"].queryset = _active_records()
        if self.is_bound and self.data.get("company_source") != "arsp":
            self.data = self.data.copy()
            self.data["record_id"] = ""

    def clean_company_source(self):
        # Older open forms did not submit a source; keep their manual behavior.
        return self.cleaned_data["company_source"] or "manual"

    def clean(self):
        values = super().clean()
        if values.get("company_source") == "arsp":
            if not values.get("record_id") and "record_id" not in self.errors:
                self.add_error("record_id", "Sélectionne une entreprise dans la base ARSP avant de lancer la recherche.")
        else:
            # A stale hidden selection must never associate a free-text search to ARSP.
            values["record_id"] = None
        return values

    def clean_coordinates(self):
        value = self.cleaned_data["coordinates"].strip()
        if self.data.get("engine") not in {"google_maps", "all"}:
            return ""
        if value:
            match = re.fullmatch(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(\d+)z", value)
            if not match or not (-90 <= float(match[1]) <= 90 and -180 <= float(match[2]) <= 180 and 3 <= int(match[3]) <= 30):
                raise forms.ValidationError("Utilise @latitude,longitude,zoomz avec des coordonnées valides et un zoom de 3 à 30.")
        return value

    def parameters(self):
        values = self.cleaned_data
        result = {"engine": values["engine"], "q": values["query"], "hl": values["language"], "no_cache": "false"}
        if values["engine"] in {"google_maps", "all"}:
            if values["engine"] == "google_maps":
                result["type"] = "search"
            if values["coordinates"]:
                result["ll"] = values["coordinates"]
        if values["engine"] != "google_maps":
            result["gl"] = values["country"]
        return result


def _check_access(request):
    if not has_role(request.user, "kam", "operator", "admin"):
        raise Http404


def _form_initial(search=None):
    parameters = search.parameters if search else {}
    company = (search.report.get("input_company") or {}) if search else {}
    return {
        "submission_id": uuid.uuid4(), "scenario": search.scenario if search else "complete",
        "company_source": "arsp" if company else "manual", "record_id": company.get("id"),
        "engine": search.engine if search else "all",
        "query": search.query if search else "entreprises logistiques Kinshasa RDC",
        "language": parameters.get("hl", "fr"), "country": parameters.get("gl", "cd"),
        "coordinates": parameters.get("ll", ""),
    }


def _page(request, form=None, search=None, **extra):
    records = _active_records()
    arsp_query = request.GET.get("arsp_q", "").strip()[:200]
    if form is None:
        initial = _form_initial(search)
        if not search:
            initial["company_source"] = "arsp" if request.GET.get("company_source") == "arsp" else "manual"
            if request.GET.get("record"):
                try:
                    record_key = int(request.GET["record"])
                except (ValueError, TypeError):
                    raise Http404 from None
                record = get_object_or_404(records, pk=record_key)
                initial.update(company_source="arsp", record_id=record.pk, query=_company_query(record))
        form = SearchForm(initial=initial)
    selected_record = None
    record_id = form["record_id"].value()
    if record_id and str(record_id).isdigit():
        selected_record = records.filter(pk=record_id).first()
    selected_company = _company_input(selected_record) if selected_record else None
    if arsp_query:
        records = records.filter(
            Q(legal_name__icontains=arsp_query) | Q(dossier_number__icontains=arsp_query)
            | Q(raw_data__RCCM__icontains=arsp_query)
            | Q(**{"raw_data__Nom Commercial__icontains": arsp_query})
        )
    arsp_page = Paginator(records.order_by("legal_name", "pk"), 10).get_page(request.GET.get("arsp_page"))
    sections = []
    if search:
        outcomes = search.report.get("engines") or [{"engine": search.engine}]
        for outcome in outcomes:
            engine = outcome["engine"]
            sections.append({
                **outcome, "label": dict(serpapi.ENGINES).get(engine, engine),
                "results": [result for result in search.report.get("results", [])
                            if result.get("engine", search.engine) == engine],
            })
    return render(request, "research/serpapi.html", {
        "form": form,
        "company_source": form["company_source"].value() or "manual",
        "selected_company": selected_company,
        "arsp_query": arsp_query, "arsp_page": arsp_page,
        "company_subject": selected_company["name"] if selected_company else "entreprises logistiques",
        "company_city": selected_company["province"] if selected_company else "Kinshasa",
        "current_search": search,
        "result_sections": sections,
        "configured": bool(settings.ONBORA_SERPAPI_API_KEY.strip()),
        "history": SerpApiSearch.objects.filter(requested_by=request.user)[:12],
        **extra,
    })


@login_required
@require_http_methods(["GET", "POST"])
def search_page(request):
    _check_access(request)
    if request.method == "POST":
        # Explicit, free account check, never performed on a normal page view.
        if request.POST.get("action") != "account":
            raise Http404
        try:
            return _page(request, quota=serpapi.account(), quota_checked=True)
        except serpapi.SerpApiError as error:
            return _page(request, account_error=str(error))
    current = None
    if request.GET.get("search"):
        try:
            search_id = int(request.GET["search"])
        except ValueError:
            raise Http404 from None
        current = get_object_or_404(SerpApiSearch, pk=search_id, requested_by=request.user)
    return _page(request, search=current)


@login_required
@require_POST
@sensitive_variables()
def create(request):
    _check_access(request)
    form = SearchForm(request.POST)
    if not form.is_valid():
        return _page(request, form=form)
    if not settings.ONBORA_SERPAPI_API_KEY.strip():
        form.add_error(None, "Ajoute SERPAPI_API_KEY dans .env, puis redémarre Onbora pour lancer le test.")
        return _page(request, form=form)
    values = form.cleaned_data
    search, created = SerpApiSearch.objects.get_or_create(
        submission_id=values["submission_id"], defaults={
            "requested_by": request.user, "scenario": values["scenario"], "query": values["query"],
            "engine": values["engine"], "parameters": form.parameters(),
        },
    )
    if search.requested_by_id != request.user.pk:
        raise Http404
    if created:
        try:
            search.report = (serpapi.search_all(search.parameters) if search.engine == "all"
                             else serpapi.search(search.parameters))
            if search.report.get("status") == "failed":
                search.state = SerpApiSearch.State.FAILED
                search.error_message = "Les trois moteurs ont échoué. Consulte le bilan des moteurs avant de relancer."
            else:
                search.state = SerpApiSearch.State.COMPLETE
        except serpapi.SerpApiError as error:
            search.error_message = str(error)
            search.state = SerpApiSearch.State.FAILED
        record = values.get("record_id")
        search.report["company_source"] = values["company_source"]
        search.report["input_company"] = _company_input(record) if record else None
        search.completed_at = timezone.now()
        search.save(update_fields=["report", "state", "error_message", "completed_at"])
    return redirect(f"{reverse('serpapi-search')}?search={search.pk}#serp-results")


def _csv_cell(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


@login_required
@require_GET
def export(request, search_id, format):
    _check_access(request)
    search = get_object_or_404(SerpApiSearch, pk=search_id, requested_by=request.user, state="complete")
    metadata = {
        "search_id": search.pk, "scenario": search.scenario, "query": search.query,
        "created_at": search.created_at.isoformat(), **search.report,
    }
    if format == "json":
        response = HttpResponse(json.dumps(metadata, ensure_ascii=False, indent=2), content_type="application/json")
    elif format == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response.write("\ufeff")
        writer = csv.writer(response)
        fields = ("kind", "title", "url", "website", "address", "phone", "category", "date", "source", "snippet", "place_id")
        writer.writerow(("query", "engine", "created_at", *fields))
        for result in search.report.get("results", []):
            writer.writerow([_csv_cell(value) for value in (
                search.query, result.get("engine", search.engine), search.created_at.isoformat(), *(result.get(field, "") for field in fields),
            )])
    else:
        raise Http404
    response["Content-Disposition"] = f'attachment; filename="serpapi-{search.pk}.{format}"'
    response["Cache-Control"] = "private, no-store"
    return response
