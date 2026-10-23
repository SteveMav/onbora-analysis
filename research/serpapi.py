"""Bounded SerpApi transport and whitelisted reports, without AI or page fetching."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from django.views.decorators.debug import sensitive_variables

ENGINES = (("google_maps", "Google Maps"), ("google", "Google Web"), ("google_news", "Google News"))
SEARCH_OPTIONS = (("all", "Recherche complète · Web + Maps + News"), *ENGINES)
SCENARIOS = (
    ("complete", "Recherche complète d’entreprise"),
    ("discovery", "Découverte d’entreprises"),
    ("profile", "Profil d’entreprise"),
    ("news", "Actualités et projets"),
    ("technology", "Technologies et fournisseurs"),
)
MAX_BYTES = 4_000_000
MAX_RESULTS = 50


class SerpApiError(RuntimeError):
    """Safe, actionable message; never expose vendor errors containing the API URL."""


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@sensitive_variables()
def _request(path: str, parameters: dict) -> dict:
    key = settings.ONBORA_SERPAPI_API_KEY.strip()
    if not key:
        raise SerpApiError("Ajoute SERPAPI_API_KEY dans le fichier .env, puis redémarre Onbora.")
    url = f"https://serpapi.com/{path}?{urlencode({**parameters, 'api_key': key})}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Onbora-SerpApi-Test/1.0"})
    try:
        with build_opener(_NoRedirects()).open(
            request, timeout=settings.ONBORA_SERPAPI_TIMEOUT_SECONDS,
        ) as response:
            raw = response.read(MAX_BYTES + 1)
    except HTTPError as error:
        messages = {
            400: "Requête refusée par SerpApi. Vérifie les mots-clés et les paramètres du moteur.",
            401: "Clé SerpApi invalide. Vérifie SERPAPI_API_KEY dans .env et redémarre Onbora.",
            403: "Accès SerpApi refusé. Vérifie les droits de ton compte.",
            429: "Quota SerpApi épuisé ou limite horaire atteinte. Consulte ton compte avant de réessayer.",
        }
        message = messages.get(error.code, "SerpApi est indisponible. Aucun nouvel essai automatique.")
        error.close()
        raise SerpApiError(message) from None
    except (URLError, TimeoutError, OSError, HTTPException):
        raise SerpApiError("SerpApi n’a pas répondu à temps ou le réseau est indisponible. Aucun nouvel essai automatique.") from None
    if len(raw) > MAX_BYTES:
        raise SerpApiError("La réponse SerpApi dépasse la limite de 4 Mo.")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise SerpApiError("SerpApi a renvoyé une réponse JSON illisible.") from None
    if not isinstance(data, dict):
        raise SerpApiError("Format de réponse SerpApi inattendu.")
    metadata = data.get("search_metadata")
    status = metadata.get("status") if isinstance(metadata, dict) else None
    # A successful search with no matches may include an explanatory error field.
    if (data.get("error") and status != "Success") or status in {"Error", "Processing"}:
        raise SerpApiError("SerpApi n’a pas terminé cette recherche. Vérifie la requête et ton compte avant de réessayer.")
    return data


def _text(value, limit=1500) -> str:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    text = str(value)
    key = settings.ONBORA_SERPAPI_API_KEY.strip()
    if key:
        text = text.replace(key, "[clé masquée]")
    return text[:limit]


def _url(value) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        return ""
    try:
        parts = urlsplit(value)
        if (parts.scheme not in {"https", "http"} or not parts.hostname
                or parts.username or parts.password or any(c.isspace() or ord(c) < 32 for c in value)):
            return ""
        if parts.hostname == "serpapi.com" or parts.hostname.endswith(".serpapi.com"):
            return ""
        if any(k.lower() in {"api_key", "apikey", "access_token", "key"} for k, _ in parse_qsl(parts.query)):
            return ""
        key = settings.ONBORA_SERPAPI_API_KEY.strip()
        if key and key in unquote(value):
            return ""
    except ValueError:
        return ""
    return value


def _items(value):
    return [item for item in value[:100] if isinstance(item, dict)] if isinstance(value, list) else []


def normalize_results(data: dict, engine: str) -> list[dict]:
    """Flatten News clusters; preserve different Maps branches sharing a website."""
    candidates = []
    if engine == "google_news":
        for item in _items(data.get("news_results")):
            candidates.append(("Actualité", item))
            if isinstance(item.get("highlight"), dict):
                candidates.append(("Actualité", item["highlight"]))
            candidates.extend(("Actualité", story) for story in _items(item.get("stories")))
    elif engine == "google_maps":
        candidates.extend(("Établissement", item) for item in _items(data.get("local_results")))
    else:
        candidates.extend(("Page web", item) for item in _items(data.get("organic_results")))
        graph = data.get("knowledge_graph")
        if isinstance(graph, dict):
            candidates.append(("Fiche Google", graph))
        local = data.get("local_results")
        if isinstance(local, dict):
            local = local.get("places")
        candidates.extend(("Établissement", item) for item in _items(local))

    results, seen = [], set()
    for kind, item in candidates:
        title = _text(item.get("title"), 500)
        if not title:
            continue
        url = _url(item.get("link"))
        website = _url(item.get("website"))
        place_id = _text(item.get("place_id"), 300)
        if kind == "Établissement" and not url:
            if place_id:
                url = "https://www.google.com/maps/search/?" + urlencode({"api": "1", "query": title, "query_place_id": place_id})
            else:
                url = "https://www.google.com/maps/search/?" + urlencode({"api": "1", "query": f"{title} {_text(item.get('address'), 500)}"})
        if not url and not website:
            continue
        identity = (kind, place_id or (title, _text(item.get("address")))) if kind == "Établissement" else (url or website)
        if identity in seen:
            continue
        seen.add(identity)
        source = item.get("source")
        if isinstance(source, dict):
            source = source.get("name")
        results.append({
            "kind": kind, "title": title, "url": url, "website": website,
            "snippet": _text(item.get("snippet") or item.get("description")),
            "address": _text(item.get("address"), 700), "phone": _text(item.get("phone"), 100),
            "category": _text(item.get("type"), 300), "place_id": place_id,
            "date": _text(item.get("date"), 100),
            "source": _text(source, 300) or urlsplit(url or website).hostname,
        })
        if len(results) >= MAX_RESULTS:
            break
    return results


def search(parameters: dict) -> dict:
    if parameters.get("engine") not in dict(ENGINES):
        raise SerpApiError("Moteur SerpApi non pris en charge.")
    started = time.monotonic()
    data = _request("search.json", parameters)
    metadata = data.get("search_metadata") or {}
    results = normalize_results(data, parameters["engine"])
    for result in results:
        result["engine"] = parameters["engine"]
    return {
        "provider": "serpapi", "parameters": parameters,
        "search_id": _text(metadata.get("id"), 100) if isinstance(metadata, dict) else "",
        "elapsed_seconds": round(time.monotonic() - started, 2), "request_count": 1,
        "results": results, "result_count": len(results),
        "website_count": sum(bool(r["website"]) for r in results),
        "address_count": sum(bool(r["address"]) for r in results),
        "phone_count": sum(bool(r["phone"]) for r in results),
    }


def search_all(parameters: dict) -> dict:
    """Three independent searches, no retries; preserve successful partial results."""
    started = time.monotonic()
    requests = []
    for engine in ("google", "google_maps", "google_news"):
        request = {"engine": engine, "q": parameters["q"], "hl": parameters["hl"], "no_cache": "false"}
        if engine == "google_maps":
            request["type"] = "search"
            if parameters.get("ll"):
                request["ll"] = parameters["ll"]
        else:
            request["gl"] = parameters["gl"]
        requests.append(request)

    engines, results = [], []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(search, request) for request in requests]
        for request, future in zip(requests, futures):
            outcome = {"engine": request["engine"], "label": dict(ENGINES)[request["engine"]], "parameters": request, "request_count": 1}
            try:
                report = future.result()
                results.extend(report["results"])
                outcome.update({"status": "complete", "result_count": report["result_count"],
                                "elapsed_seconds": report["elapsed_seconds"], "search_id": report["search_id"]})
            except SerpApiError as error:
                outcome.update({"status": "failed", "result_count": 0, "error": str(error)})
            engines.append(outcome)
    succeeded = sum(item["status"] == "complete" for item in engines)
    return {
        "provider": "serpapi", "parameters": parameters, "engines": engines,
        "status": "complete" if succeeded == 3 else "partial" if succeeded else "failed",
        "elapsed_seconds": round(time.monotonic() - started, 2), "request_count": 3,
        "successful_request_count": succeeded, "results": results, "result_count": len(results),
        "website_count": sum(bool(r["website"]) for r in results),
        "address_count": sum(bool(r["address"]) for r in results),
        "phone_count": sum(bool(r["phone"]) for r in results),
    }


def account() -> dict:
    data = _request("account.json", {})
    # Account API also returns api_key, email and account_id: never persist them.
    allowed = ("total_searches_left", "this_month_usage", "searches_per_month", "account_rate_limit_per_hour")
    return {field: data[field] for field in allowed if type(data.get(field)) is int}
