"""Deterministic, evidence-backed business-sector segmentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .web_research import CompanySeed, normalize


TAXONOMY_VERSION = "onbora-sector-v1"


@dataclass(frozen=True)
class SectorEvidence:
    evidence_id: int
    title: str
    publisher: str
    relationship: str
    excerpt: str


SECTORS: tuple[dict[str, Any], ...] = (
    {
        "segment_id": "mining_extraction",
        "label": "Mines et extraction",
        "keywords": (
            "mine", "mines", "minier", "miniere", "extraction miniere", "cuivre",
            "cobalt", "carriere", "metallurgie",
        ),
    },
    {
        "segment_id": "transport_logistics",
        "label": "Transport et logistique",
        "keywords": (
            "transport", "logistique", "logistiques", "transit", "fret", "entreposage", "livraison",
            "commissionnaire en douane", "chaine d approvisionnement",
        ),
    },
    {
        "segment_id": "commerce_distribution",
        "label": "Commerce et distribution",
        "keywords": (
            "commerce", "distribution", "retail", "vente au detail", "grossiste",
            "supermarche", "boutique", "e commerce",
        ),
    },
    {
        "segment_id": "financial_services",
        "label": "Banque, assurance et services financiers",
        "keywords": (
            "banque", "bancaire", "microfinance", "fintech", "assurance",
            "services financiers", "institution financiere",
        ),
    },
    {
        "segment_id": "construction_real_estate",
        "label": "Construction et immobilier",
        "keywords": (
            "construction", "batiment", "travaux publics", "immobilier", "genie civil",
            "architecture", "promotion immobiliere",
        ),
    },
    {
        "segment_id": "industry_manufacturing",
        "label": "Industrie et fabrication",
        "keywords": (
            "industrie", "industriel", "manufacture", "fabrication", "usine",
            "agroalimentaire", "production industrielle",
        ),
    },
    {
        "segment_id": "energy_utilities",
        "label": "Énergie, eau et hydrocarbures",
        "keywords": (
            "energie", "electricite", "petrole", "gaz", "hydrocarbures", "solaire",
            "distribution d eau", "production electrique",
        ),
    },
    {
        "segment_id": "telecom_technology",
        "label": "Télécommunications et technologies",
        "keywords": (
            "telecommunication", "telecommunications", "telecom", "informatique",
            "technologie", "numerique", "logiciel", "software", "internet", "data center",
        ),
    },
    {
        "segment_id": "health_pharma",
        "label": "Santé et pharmaceutique",
        "keywords": (
            "sante", "medical", "hopital", "clinique", "pharmacie", "pharmaceutique",
            "laboratoire medical",
        ),
    },
    {
        "segment_id": "education_training",
        "label": "Éducation et formation",
        "keywords": (
            "education", "ecole", "universite", "formation", "enseignement", "academie",
        ),
    },
    {
        "segment_id": "agriculture_agribusiness",
        "label": "Agriculture et agro-industrie",
        "keywords": (
            "agriculture", "agricole", "agro industrie", "agro pastoral", "elevage",
            "peche", "exploitation agricole",
        ),
    },
    {
        "segment_id": "hospitality_tourism",
        "label": "Hôtellerie, restauration et tourisme",
        "keywords": (
            "hotel", "hotellerie", "restaurant", "restauration", "tourisme", "voyage",
            "agence de voyage",
        ),
    },
    {
        "segment_id": "public_ngo",
        "label": "Secteur public, ONG et développement",
        "keywords": (
            "administration publique", "service public", "ministere", "organisme public",
            "ong", "humanitaire", "association", "fondation", "developpement communautaire",
        ),
    },
    {
        "segment_id": "professional_services",
        "label": "Services professionnels",
        "keywords": (
            "conseil", "consulting", "audit", "juridique", "comptable", "recrutement",
            "bureau d etudes", "services aux entreprises",
        ),
    },
    {
        "segment_id": "media_communication",
        "label": "Médias, communication et publicité",
        "keywords": (
            "media", "communication", "publicite", "marketing", "presse", "radio",
            "television", "production audiovisuelle",
        ),
    },
)


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = normalize(phrase)
    return bool(normalized_phrase and f" {normalized_phrase} " in f" {text} ")


def _matched_keywords(text: str, keywords: Iterable[str]) -> list[str]:
    return [keyword for keyword in keywords if _contains_phrase(text, keyword)]


def build_sector_segmentation(
    company: CompanySeed,
    evidence: Iterable[SectorEvidence],
    identity_status: str,
) -> dict[str, Any]:
    """Classify a company into a controlled sector taxonomy without inventing facts."""
    evidence_items = list(evidence)
    seed_text = normalize(company.sector)
    ranked: list[dict[str, Any]] = []

    for sector in SECTORS:
        seed_keywords = _matched_keywords(seed_text, sector["keywords"])
        evidence_ids: list[int] = []
        evidence_keywords: set[str] = set()
        publishers: set[str] = set()
        evidence_points = 0

        for item in evidence_items:
            matches = _matched_keywords(normalize(f"{item.title}\n{item.excerpt}"), sector["keywords"])
            if not matches:
                continue
            evidence_ids.append(item.evidence_id)
            evidence_keywords.update(matches)
            publisher = normalize(item.publisher) or f"evidence-{item.evidence_id}"
            if publisher in publishers:
                continue
            publishers.add(publisher)
            evidence_points += 3 if item.relationship == "independent" else 2

        score = (6 if seed_keywords else 0) + min(evidence_points, 9)
        if score:
            ranked.append({
                "segment_id": sector["segment_id"],
                "label": sector["label"],
                "score": score,
                "seed_match": bool(seed_keywords),
                "matched_keywords": sorted(set(seed_keywords) | evidence_keywords)[:6],
                "evidence_ids": list(dict.fromkeys(evidence_ids)),
                "publisher_count": len(publishers),
            })

    ranked.sort(
        key=lambda item: (
            -item["score"],
            -int(item["seed_match"]),
            -item["publisher_count"],
            item["label"],
        )
    )
    if not ranked:
        return {
            "status": "unknown",
            "taxonomy_version": TAXONOMY_VERSION,
            "raw_activity": company.sector,
            "message": (
                "L’activité disponible ne correspond pas encore à un secteur de la taxonomie. "
                "Une vérification humaine ou une source décrivant l’activité est nécessaire."
            ),
            "primary": None,
            "alternatives": [],
        }

    primary = ranked[0]
    if primary["seed_match"] and primary["evidence_ids"]:
        confidence = "élevée"
        reason = "L’activité ARSP est corroborée par au moins une source publique liée à l’entreprise."
    elif primary["publisher_count"] >= 2 and identity_status in {"confirmed", "probable"}:
        confidence = "élevée"
        reason = "Au moins deux éditeurs publics concordants décrivent cette activité."
    elif primary["seed_match"]:
        confidence = "moyenne"
        reason = "Le secteur est déduit de l’activité déclarée dans la base ARSP et reste à confirmer publiquement."
    else:
        confidence = "moyenne" if identity_status in {"confirmed", "probable"} else "faible"
        reason = "Une source publique liée à l’entreprise décrit cette activité, sans confirmation dans la donnée ARSP."

    primary = {**primary, "confidence": confidence, "reason": reason}
    alternatives = [
        item for item in ranked[1:]
        if item["score"] >= max(3, primary["score"] - 3)
    ][:2]
    return {
        "status": "complete",
        "taxonomy_version": TAXONOMY_VERSION,
        "raw_activity": company.sector,
        "primary": primary,
        "alternatives": alternatives,
    }
