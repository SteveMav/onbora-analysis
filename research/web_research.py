"""Bounded public-web discovery and deterministic relevance assessment.

The code is adapted from the ``essai`` prototype, but exposes framework-neutral
components so the Django worker can persist every attempt before presenting it.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from trafilatura import extract

from .text_utils import clean_excel_text, company_name_variants


@dataclass(frozen=True)
class CompanySeed:
    legal_name: str
    trade_name: str = ""
    sector: str = ""
    province: str = ""
    rccm: str = ""
    tax_number: str = ""
    address: str = ""


@dataclass(frozen=True)
class QuerySpec:
    category: str
    query: str


@dataclass(frozen=True)
class SearchHit:
    query: str
    category: str
    rank: int
    title: str
    url: str
    snippet: str
    discovery_score: int
    provider: str = "searxng"


@dataclass(frozen=True)
class PageAssessment:
    verdict: str
    score: int
    source_type: str
    relationship: str
    reasons: tuple[str, ...]
    excerpt: str
    final_url: str
    content_hash: str = ""
    error: str = ""


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(character for character in value if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", value))


def meaningful_tokens(value: str) -> set[str]:
    ignored = {
        "avec", "dans", "pour", "sarl", "sarlu", "sprl", "sas", "societe",
        "entreprise", "company", "congo", "republique", "democratique", "group",
        "groupe", "holding", "international", "service", "services", "solution",
        "solutions", "general",
    }
    return {token for token in normalize(value).split() if len(token) >= 4 and token not in ignored}


def company_from_snapshot(snapshot: dict[str, Any]) -> CompanySeed:
    value = snapshot.get("input_snapshot", {})
    return CompanySeed(
        legal_name=clean_excel_text(value.get("legal_name") or ""),
        trade_name=clean_excel_text(value.get("trade_name") or ""),
        sector=clean_excel_text(value.get("activity_arsp") or ""),
        province=clean_excel_text(value.get("province") or ""),
        rccm=clean_excel_text(value.get("rccm") or ""),
        tax_number=clean_excel_text(value.get("tax_number") or ""),
        address=clean_excel_text(value.get("address_arsp") or ""),
    )


def build_query_plan(company: CompanySeed) -> list[QuerySpec]:
    """Build several focused queries instead of one over-constrained query."""
    if not company.legal_name:
        raise ValueError("La dénomination de l’entreprise est requise.")
    names = company_name_variants(company.legal_name)
    name = f'"{names[0]}"'
    candidates = [QuerySpec("identity", name)]
    if company.rccm:
        candidates.insert(0, QuerySpec("registry", f'{name} "{company.rccm}"'))
    if company.province:
        candidates.append(QuerySpec("location", f"{name} {company.province}"))
    candidates.append(QuerySpec("sector", f"{name} activité entreprise secteur"))
    sector_words = " ".join(sorted(meaningful_tokens(company.sector))[:4])
    if sector_words:
        candidates.append(QuerySpec("activity", f"{name} {sector_words}"))
    if len(names) > 1:
        brand = f'"{names[1]}"'
        candidates.append(QuerySpec("brand", brand))
        if company.province:
            candidates.append(QuerySpec("brand_location", f"{brand} {company.province}"))
    if getattr(settings, "ONBORA_LEAD_QUALIFICATION_ENABLED", True):
        candidates.extend((
            QuerySpec("lead_network", f'{name} agences succursales bureaux dépôts'),
            QuerySpec("lead_customer", f'{name} application paiement clients plateforme'),
            QuerySpec("lead_mobility", f'{name} flotte véhicules équipements logistique'),
            QuerySpec("lead_collaboration", f'{name} Microsoft 365 Teams télétravail collaboration'),
            QuerySpec("lead_cloud", f'{name} cloud datacenter serveurs sauvegarde'),
        ))

    seen: set[str] = set()
    result: list[QuerySpec] = []
    for candidate in candidates:
        key = normalize(candidate.query)
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def canonicalize_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL HTTP invalide")
    hostname = parsed.hostname.casefold().rstrip(".")
    port = parsed.port
    netloc = hostname
    if port and not ((parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443)):
        netloc = f"{hostname}:{port}"
    path = parsed.path or "/"
    tracking_keys = {"fbclid", "gclid", "mc_cid", "mc_eid"}
    query_items = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in tracking_keys
    ]
    query = urllib.parse.urlencode(sorted(query_items))
    return urllib.parse.urlunsplit((parsed.scheme.casefold(), netloc, path, query, ""))


def source_classification(url: str, company: CompanySeed) -> tuple[str, str]:
    host = (urllib.parse.urlsplit(url).hostname or "").casefold().removeprefix("www.")
    if host.endswith((".gouv.cd", ".gov.cd")) or host in {"arsp.cd", "guichetunique.cd"}:
        return "registry", "independent"
    if host.endswith(("facebook.com", "linkedin.com", "instagram.com", "x.com", "twitter.com", "youtube.com")):
        return "social", "discovery_only"
    if host.endswith(("scribd.com", "goafricaonline.com", "africabizinfo.com", "pagesjaunes.cd")):
        return "directory", "discovery_only"
    host_words = set(re.findall(r"[a-z0-9]+", host))
    if host_words & meaningful_tokens(company.legal_name):
        return "official", "first_party"
    return "other", "independent"


def rank_search_hit(title: str, snippet: str, url: str, company: CompanySeed) -> int:
    searchable = normalize(f"{title}\n{snippet}\n{url}")
    words = set(searchable.split())
    legal = normalize(company.legal_name)
    trade = normalize(company.trade_name)
    score = 0
    exact_name_match = bool(legal and legal in searchable)
    trade_match = bool(trade and len(trade) >= 5 and trade in searchable)
    if exact_name_match:
        score += 10
    elif trade_match:
        score += 7
    name_tokens = meaningful_tokens(company.legal_name)
    matched_name_tokens = name_tokens & words
    score += min(6, len(matched_name_tokens) * 2)
    specific_match = False
    for specific in (company.rccm, company.tax_number):
        if specific and normalize(specific) in searchable:
            score += 12
            specific_match = True
    if company.province and normalize(company.province) in searchable:
        score += 2
    score += min(3, len(meaningful_tokens(company.sector) & words))
    source_type, relationship = source_classification(url, company)
    if source_type == "registry":
        score += 3
    if relationship == "discovery_only":
        score -= 1
    token_coverage = len(matched_name_tokens) / len(name_tokens) if name_tokens else 0
    if not exact_name_match and not trade_match and not specific_match and token_coverage < 0.75:
        score -= 8
    if not matched_name_tokens and not specific_match:
        score -= 10
    return score


def relevant_excerpt(text: str, company: CompanySeed, limit: int = 1600) -> str:
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+|\n+", text) if sentence.strip()]
    company_terms = meaningful_tokens(" ".join((
        company.legal_name, company.trade_name, company.sector, company.province, company.address,
    )))
    opportunity_terms = meaningful_tokens(
        "agences succursales bureaux dépôts entrepôts implantations multisite application plateforme "
        "paiement encaissement clients hotline notifications flotte véhicules camions engins logistique "
        "livraison équipements machines télémétrie géolocalisation terrain collaboration télétravail "
        "visioconférence cybersécurité vulnérabilités serveurs datacenter cloud sauvegarde reprise"
        " mines extraction transport transit commerce distribution banque assurance construction immobilier"
        " industrie énergie télécommunications informatique santé pharmacie éducation agriculture hôtellerie"
        " tourisme conseil audit médias publicité"
    )
    company_ranked = sorted(
        enumerate(sentences),
        key=lambda item: (len(meaningful_tokens(item[1]) & company_terms), -item[0]),
        reverse=True,
    )
    chosen_indexes = [
        index for index, sentence in company_ranked
        if meaningful_tokens(sentence) & company_terms
    ][:3]
    opportunity_ranked = sorted(
        enumerate(sentences),
        key=lambda item: (len(meaningful_tokens(item[1]) & opportunity_terms), -item[0]),
        reverse=True,
    )
    for index, sentence in opportunity_ranked:
        if index in chosen_indexes or not meaningful_tokens(sentence) & opportunity_terms:
            continue
        chosen_indexes.append(index)
        if len(chosen_indexes) >= 6:
            break
    chosen = [sentences[index] for index in chosen_indexes]
    excerpt = "\n\n".join(chosen) if chosen else "Aucun passage clairement pertinent n’a été extrait."
    return excerpt[:limit].rstrip()


def assess_text(company: CompanySeed, title: str, text: str, url: str) -> PageAssessment:
    searchable = normalize(f"{title}\n{text}")
    words = set(searchable.split())
    reasons: list[str] = []
    score = 0
    legal = normalize(company.legal_name)
    trade = normalize(company.trade_name)
    legal_match = bool(legal and legal in searchable)
    trade_match = bool(trade and len(trade) >= 5 and trade in searchable)
    if legal_match:
        score += 5
        reasons.append("nom légal trouvé")
    elif trade_match:
        score += 3
        reasons.append("nom commercial trouvé")

    strong_match = False
    for label, value in (("RCCM", company.rccm), ("numéro fiscal", company.tax_number)):
        if value and normalize(value) in searchable:
            score += 5
            strong_match = True
            reasons.append(f"{label} exact trouvé")
    normalized_address = normalize(company.address)
    if len(normalized_address) >= 12 and normalized_address in searchable:
        score += 3
        strong_match = True
        reasons.append("adresse ARSP concordante")
    if company.province and normalize(company.province) in searchable:
        score += 1
        reasons.append("province ou ville concordante")
    sector_tokens = meaningful_tokens(company.sector)
    matched_sector = sector_tokens & words
    if sector_tokens and len(matched_sector) >= max(1, len(sector_tokens) // 2):
        score += 2
        reasons.append("activité concordante")
    elif matched_sector:
        score += 1
        reasons.append("activité partiellement concordante")

    if strong_match and (legal_match or trade_match):
        verdict = "Pertinente"
    elif legal_match and score >= 6:
        verdict = "Pertinente"
    elif legal_match or (trade_match and score >= 4):
        verdict = "À vérifier"
    else:
        verdict = "Hors sujet probable"
        reasons.append("pas assez d’éléments pour relier la page à l’entreprise")
    source_type, relationship = source_classification(url, company)
    return PageAssessment(
        verdict=verdict,
        score=score,
        source_type=source_type,
        relationship=relationship,
        reasons=tuple(reasons),
        excerpt=relevant_excerpt(text, company),
        final_url=url,
    )


def validate_public_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("URL non HTTP refusée")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ValueError("nom de domaine introuvable") from error
    if not addresses:
        raise ValueError("nom de domaine sans adresse")
    for address in addresses:
        if not ipaddress.ip_address(address[4][0]).is_global:
            raise ValueError("adresse locale ou privée refusée")


class _PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        validate_public_url(new_url)
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


class SearxngClient:
    def __init__(self, base_url: str | None = None, timeout: int = 25) -> None:
        self.base_url = (base_url or settings.ONBORA_SEARXNG_URL).rstrip("/")
        self.timeout = timeout
        self.last_warnings: tuple[tuple[str, str], ...] = ()

    def search(self, spec: QuerySpec) -> list[SearchHit]:
        self.last_warnings = ()
        params = urllib.parse.urlencode({"q": spec.query, "format": "json", "language": "fr", "safesearch": "1"})
        request = urllib.request.Request(
            f"{self.base_url}/search?{params}",
            headers={"User-Agent": "Onbora-Research/0.2"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"SearXNG a répondu avec l’erreur HTTP {error.code}.") from error
        except urllib.error.URLError as error:
            raise RuntimeError("SearXNG local n’est pas joignable.") from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RuntimeError("SearXNG a renvoyé une réponse illisible.") from error
        values = payload.get("results", [])
        warnings: list[tuple[str, str]] = []
        for warning in payload.get("unresponsive_engines", []):
            if isinstance(warning, (list, tuple)) and len(warning) >= 2:
                warnings.append((str(warning[0])[:100], str(warning[1])[:300]))
        self.last_warnings = tuple(warnings)
        if not isinstance(values, list):
            raise RuntimeError("SearXNG n’a pas renvoyé de liste de résultats.")
        hits: list[SearchHit] = []
        for rank, value in enumerate(values[: settings.ONBORA_SEARCH_RESULTS_PER_QUERY], start=1):
            if not isinstance(value, dict):
                continue
            url = str(value.get("url") or "")
            try:
                canonicalize_url(url)
            except ValueError:
                continue
            hits.append(SearchHit(
                query=spec.query,
                category=spec.category,
                rank=rank,
                title=str(value.get("title") or "Sans titre")[:1000],
                url=url,
                snippet=str(value.get("content") or ""),
                discovery_score=0,
            ))
        return hits


class PageFetcher:
    def __init__(self, timeout: int = 12) -> None:
        self.timeout = timeout
        self.opener = urllib.request.build_opener(_PublicRedirectHandler())

    def analyze(self, hit: SearchHit, company: CompanySeed) -> PageAssessment:
        try:
            validate_public_url(hit.url)
            request = urllib.request.Request(
                hit.url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Onbora-Research/0.2; internal prototype)",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            with self.opener.open(request, timeout=self.timeout) as response:
                final_url = response.geturl()
                validate_public_url(final_url)
                content_type = response.headers.get_content_type()
                if content_type not in {"text/html", "application/xhtml+xml"}:
                    raise ValueError(f"format non analysé : {content_type}")
                raw = response.read(settings.ONBORA_MAX_PAGE_BYTES + 1)
                if len(raw) > settings.ONBORA_MAX_PAGE_BYTES:
                    raise ValueError("page trop volumineuse")
                charset = response.headers.get_content_charset() or "utf-8"
                html = raw.decode(charset, errors="replace")
            text = extract(html, url=final_url, include_comments=False, include_tables=False, favor_precision=True)
            if not text or len(text.strip()) < 80:
                raise ValueError("aucun texte principal exploitable")
            assessment = assess_text(company, hit.title, text, final_url)
            return PageAssessment(
                **{**assessment.__dict__, "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()}
            )
        except (ValueError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as error:
            source_type, relationship = source_classification(hit.url, company)
            return PageAssessment(
                verdict="Inaccessible",
                score=0,
                source_type=source_type,
                relationship=relationship,
                reasons=("la page n’a pas pu être analysée",),
                excerpt="",
                final_url=hit.url,
                error=str(error)[:500],
            )
