"""Bounded public-web discovery and deterministic relevance assessment.

The code is adapted from the ``essai`` prototype, but exposes framework-neutral
components so the Django worker can persist every attempt before presenting it.
"""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
import textwrap
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
    email: str = ""


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
        "solutions", "general", "specifie", "renseigne", "inconnu",
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
        email=clean_excel_text(value.get("email_arsp") or ""),
    )


def company_names(company: CompanySeed) -> list[str]:
    return list(dict.fromkeys(
        normalize(name) for name in [*company_name_variants(company.legal_name), company.trade_name]
        if len(normalize(name)) >= 5
    ))


def company_website_domain(company: CompanySeed) -> str:
    """Use a company-specific ARSP email domain, never a shared mail provider."""
    match = re.fullmatch(r"[^\s@]+@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", company.email)
    if not match:
        return ""
    domain = match.group(1).casefold().rstrip(".")
    label = domain.split(".")[0]
    # Require a distinctive name match as well as the structured seed contact.
    brands = {name.replace(" ", "") for name in company_names(company)}
    if len(label) < 5 or label not in brands:
        return ""
    return domain


def is_seed_website(url: str, company: CompanySeed) -> bool:
    domain = company_website_domain(company)
    host = (urllib.parse.urlsplit(url).hostname or "").casefold().rstrip(".")
    return bool(domain and (host == domain or host.endswith("." + domain)))


def build_query_plan(company: CompanySeed) -> list[QuerySpec]:
    """Resolve the company before looking for commercial opportunities."""
    if not company.legal_name:
        raise ValueError("La dénomination de l’entreprise est requise.")
    names = company_name_variants(company.legal_name)
    name = f'"{names[0]}"'
    candidates = [QuerySpec("identity", name)]
    if company.rccm:
        candidates.insert(0, QuerySpec("registry", f'"{company.rccm}"'))
        candidates.insert(1, QuerySpec("registry_name", f'{name} "{company.rccm}"'))
    candidates.append(QuerySpec("arsp", f"site:arsp.cd {name}"))
    if company.province:
        candidates.append(QuerySpec("location", f"{name} {company.province}"))
    candidates.append(QuerySpec("sector", f"{name} activité entreprise secteur"))
    sector_words = " ".join(sorted(meaningful_tokens(company.sector))[:4])
    if normalize(company.sector) in {"non specifie", "non renseigne", "inconnu"}:
        sector_words = ""
    if sector_words:
        candidates.append(QuerySpec("activity", f"{name} {sector_words}"))
    if len(names) > 1:
        brand = f'"{names[1]}"'
        candidates.append(QuerySpec("brand", brand))
        if company.province:
            candidates.append(QuerySpec("brand_location", f"{brand} {company.province}"))
        candidates.append(QuerySpec("brand_country", f"{brand} RDC Congo"))
    if domain := company_website_domain(company):
        candidates.append(QuerySpec("website", f"site:{domain}"))
    seen: set[str] = set()
    result: list[QuerySpec] = []
    for candidate in candidates:
        key = normalize(candidate.query)
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def build_lead_query_plan(company: CompanySeed) -> list[QuerySpec]:
    """Run enrichment only after a page has established company identity."""
    name = f'"{company_name_variants(company.legal_name)[0]}"'
    return [
        QuerySpec("lead_network", f'{name} agences succursales bureaux dépôts'),
        QuerySpec("lead_customer", f'{name} application paiement clients plateforme'),
        QuerySpec("lead_mobility", f'{name} flotte véhicules équipements logistique'),
        QuerySpec("lead_collaboration", f'{name} Microsoft 365 Teams télétravail collaboration'),
        QuerySpec("lead_cloud", f'{name} cloud datacenter serveurs sauvegarde'),
    ]


def build_profile_query_plan(company: CompanySeed) -> list[QuerySpec]:
    """Look for practical facts after identity, independently of the offer catalogue."""
    brand = company.trade_name or company_name_variants(company.legal_name)[-1]
    target = f'"{brand}" RDC {company.province}'.strip()
    if domain := company_website_domain(company):
        target = f"site:{domain}"
    return [
        QuerySpec("profile_activity", f"{target} présentation activités produits services"),
        QuerySpec("profile_contact", f"{target} contact adresse siège implantations"),
    ]


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
    if host.endswith((".gouv.cd", ".gov.cd", ".arsp.cd")) or host in {"arsp.cd", "guichetunique.cd"}:
        return "registry", "independent"
    if host.endswith(("facebook.com", "linkedin.com", "instagram.com", "x.com", "twitter.com", "youtube.com")):
        return "social", "discovery_only"
    if host.endswith(("scribd.com", "goafricaonline.com", "africabizinfo.com", "pagesjaunes.cd")):
        return "directory", "discovery_only"
    host_words = set(re.findall(r"[a-z0-9]+", host))
    if host_words & meaningful_tokens(company.legal_name):
        # A matching hostname is a lead, not proof that the company owns it.
        return "other", "discovery_only"
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
    elif any(f" {name} " in f" {searchable} " for name in company_names(company)):
        score += 7
    if is_seed_website(url, company):
        score += 15
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
    # Keep facts near an actual name mention. A generic page can describe many
    # other companies, whose activities must not enter the summary packet.
    names = company_names(company)
    passages = [part.strip() for part in text.splitlines() if part.strip()]
    chosen: list[str] = []
    for passage in passages:
        normalized = f" {normalize(passage)} "
        if not any(f" {name} " in normalized for name in names):
            continue
        if len(passage) > 1200:
            match = None
            for name in [*company_name_variants(company.legal_name), company.trade_name]:
                if name and (match := re.search(re.escape(name), passage, re.IGNORECASE)):
                    break
            if match:
                passage = passage[max(0, match.start() - 150):match.end() + 900]
        if passage not in chosen:
            chosen.append(passage)
        if len("\n\n".join(chosen)) >= limit:
            break
    return "\n\n".join(chosen)[:limit].rstrip()


def website_profile_excerpt(text: str, limit: int = 4800) -> str:
    """Keep the introduction and useful late-page facts on an attached company site."""
    if len(text) <= limit:
        return text.rstrip()
    passages = [
        part for line in text.splitlines()
        for part in textwrap.wrap(line.strip(), width=1000, break_long_words=False, break_on_hyphens=False)
    ]
    chosen = {index for index in range(min(3, len(passages)))}
    useful = {
        "activite", "agence", "adresse", "avenue", "bureau", "client", "contact",
        "creation", "email", "implantation", "partenaire", "produit", "projet",
        "service", "siege", "specialite", "telephone", "ville", "coordonnees", "about",
        "address", "office", "phone", "product", "headquarters",
    }
    ranked = sorted(range(len(passages)), key=lambda index: (
        bool("@" in passages[index] or re.search(r"\+\d[\d ()-]{7,}", passages[index])),
        len({variant for word in normalize(passages[index]).split() for variant in (word, word.removesuffix("s"))} & useful),
        -index,
    ), reverse=True)
    # Budget per passage prevents one large paragraph from hiding footer contacts.
    budget = sum(min(len(passages[index]), 1000) + 2 for index in chosen)
    for index in ranked:
        if index in chosen:
            continue
        if not ({variant for word in normalize(passages[index]).split() for variant in (word, word.removesuffix("s"))} & useful
                or "@" in passages[index]
                or re.search(r"\+\d[\d ()-]{7,}", passages[index])):
            continue
        cost = min(len(passages[index]), 1000) + 2
        if budget + cost <= limit:
            chosen.add(index)
            budget += cost
    return "\n\n".join(passages[index][:1000] for index in sorted(chosen))[:limit].rstrip()


def assess_text(company: CompanySeed, title: str, text: str, url: str) -> PageAssessment:
    reasons: list[str] = []
    score = 0
    legal = normalize(company.legal_name)
    trade = normalize(company.trade_name)
    brands = [name for name in company_names(company) if name != legal]
    passages = [normalize(part) for part in text.splitlines() if part.strip()]
    matches = [part for part in passages if (
        legal and f" {legal} " in f" {part} "
    ) or (
        any(f" {brand} " in f" {part} " for brand in brands)
    )]
    nearby = max(matches, key=lambda part: (
        int(bool(company.rccm and normalize(company.rccm) in part))
        + int(bool(company.tax_number and normalize(company.tax_number) in part)),
        int(bool(legal and f" {legal} " in f" {part} ")),
    ), default="")
    legal_match = bool(legal and f" {legal} " in f" {nearby} ")
    trade_match = bool(trade and len(trade) >= 5 and f" {trade} " in f" {nearby} ")
    brand_match = next((brand for brand in brands if f" {brand} " in f" {nearby} "), "")
    if len(nearby) > 900:
        matched_name = legal if legal_match else brand_match
        position = nearby.find(matched_name)
        nearby = nearby[max(0, position - 250):position + len(matched_name) + 350]
    nearby_words = set(nearby.split())
    if legal_match:
        score += 5
        reasons.append("nom légal trouvé")
    elif trade_match or brand_match:
        score += 3
        reasons.append("nom commercial trouvé")

    strong_match = False
    if (legal_match or brand_match) and is_seed_website(url, company):
        score += 5
        strong_match = True
        reasons.append("domaine du contact ARSP concordant")
    for label, value in (("RCCM", company.rccm), ("numéro fiscal", company.tax_number)):
        if value and f" {normalize(value)} " in f" {nearby} ":
            score += 5
            strong_match = True
            reasons.append(f"{label} exact trouvé")
    normalized_address = normalize(company.address)
    if len(normalized_address) >= 12 and f" {normalized_address} " in f" {nearby} ":
        score += 3
        strong_match = True
        reasons.append("adresse ARSP concordante")
    if company.province and f" {normalize(company.province)} " in f" {nearby} ":
        score += 1
        reasons.append("province ou ville concordante")
    sector_tokens = meaningful_tokens(company.sector)
    matched_sector = sector_tokens & nearby_words
    if sector_tokens and len(matched_sector) >= max(1, len(sector_tokens) // 2):
        score += 2
        reasons.append("activité concordante")
    elif matched_sector:
        score += 1
        reasons.append("activité partiellement concordante")

    if strong_match and (legal_match or trade_match or brand_match):
        verdict = "Pertinente"
    elif legal_match or trade_match or brand_match:
        verdict = "À vérifier"
    else:
        verdict = "Hors sujet probable"
        reasons.append("pas assez d’éléments pour relier la page à l’entreprise")
    source_type, relationship = source_classification(url, company)
    seed_website = is_seed_website(url, company) and bool(legal_match or brand_match)
    if seed_website:
        source_type, relationship = "official", "first_party"
    return PageAssessment(
        verdict=verdict,
        score=score,
        source_type=source_type,
        relationship=relationship,
        reasons=tuple(reasons),
        excerpt=website_profile_excerpt(text) if seed_website else relevant_excerpt(text, company),
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


class _RowText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)


class _PageTitle(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.parts.append(data)


class _WebsiteContacts(HTMLParser):
    """Recover company footer/address blocks discarded by main-text extraction."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.parts: list[str] = []
        self.blocks: list[tuple[str, bool]] = []

    def _in_scope(self):
        return any(tag in {"footer", "address"} for tag in self.tags)

    def _flush(self):
        text = clean_excel_text(" ".join(self.parts))
        if text:
            self.blocks.append((text, "address" in self.tags))
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "div", "li", "address", "br"} and self._in_scope():
            self._flush()
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.tags.append(tag)

    def handle_endtag(self, tag):
        if tag in {"p", "div", "li", "address", "footer"} and self._in_scope():
            self._flush()
        for index in range(len(self.tags) - 1, -1, -1):
            if self.tags[index] == tag:
                del self.tags[index:]
                break

    def handle_data(self, data):
        if self._in_scope() and not any(tag in {"script", "style", "noscript"} for tag in self.tags):
            self.parts.append(data)


def _website_contacts(html: str) -> str:
    parser = _WebsiteContacts()
    parser.feed(html)
    parser._flush()
    blocks = []
    for text, is_address in parser.blocks:
        if is_address or "@" in text or re.search(r"\+\d[\d ()-]{7,}", text) or re.search(
            r"\b(?:adresse|address|avenue|boulevard|siege|telephone|phone|email|courriel)\b", normalize(text),
        ):
            if text not in blocks:
                blocks.append(text[:1000])
    return "\n".join(blocks)[:1600]


def _is_arsp_page(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").casefold()
    return host == "arsp.cd" or host.endswith(".arsp.cd")


def _arsp_matching_rows(html: str, company: CompanySeed) -> str:
    """Extract matching rows from ARSP's large, sometimes malformed tables."""
    names = [name.casefold() for name in company_name_variants(company.legal_name)]
    if company.trade_name:
        names.append(company.trade_name.casefold())
    lower = html.casefold()
    rows: list[str] = []
    seen: set[tuple[int, int]] = set()
    for name in names:
        if len(name) < 5:
            continue
        start = 0
        while len(rows) < 12:
            position = lower.find(name, start)
            if position < 0:
                break
            start = position + len(name)
            left = lower.rfind("</tr>", 0, position) + len("</tr>")
            right = lower.find("</tr>", position)
            if right < 0 or right - left > 12_000:
                continue
            bounds = (left, right)
            if bounds in seen:
                continue
            seen.add(bounds)
            parser = _RowText()
            parser.feed(html[left:right])
            row = " | ".join(parser.parts)
            if name in row.casefold():
                rows.append(row)
    rccm = normalize(company.rccm)
    matching_rccm = [row for row in rows if rccm and f" {rccm} " in f" {normalize(row)} "]
    return "\n".join(matching_rccm or rows)


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
                max_bytes = settings.ONBORA_MAX_PAGE_BYTES
                if _is_arsp_page(final_url):
                    max_bytes = max(max_bytes, settings.ONBORA_MAX_ARSP_PAGE_BYTES)
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise ValueError("page trop volumineuse")
                charset = response.headers.get_content_charset() or "utf-8"
                html = raw.decode(charset, errors="replace")
            text = _arsp_matching_rows(html, company) if _is_arsp_page(final_url) else ""
            if not text:
                text = extract(html, url=final_url, include_comments=False, include_tables=True, favor_precision=True)
            if not text or len(text.strip()) < 80:
                raise ValueError("aucun texte principal exploitable")
            # Wix and similar sites often render their brand in an image or
            # footer removed by extraction. Only trust the fetched HTML title,
            # and only on the company-specific domain in the ARSP contact.
            if is_seed_website(final_url, company) and not _is_arsp_page(final_url):
                parser = _PageTitle()
                parser.feed(html)
                title = clean_excel_text(" ".join(parser.parts))[:500]
                if title:
                    text = title + "\n" + text
            assessment = assess_text(company, hit.title, text, final_url)
            # Supplement only a site already attached by the fetched name and
            # registry domain. A footer alone must never establish ownership.
            if assessment.relationship == "first_party" and (contacts := _website_contacts(html)):
                text += "\n\nCoordonnées publiées sur le site de l’entreprise\n" + contacts
                assessment = PageAssessment(**{
                    **assessment.__dict__, "excerpt": website_profile_excerpt(text),
                })
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
