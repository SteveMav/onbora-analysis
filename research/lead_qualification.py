"""Evidence-backed lead qualification for the first Orange B2B journeys."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from django.conf import settings

from .web_research import CompanySeed, normalize


class LeadQualificationError(RuntimeError):
    """Raised when the configured commercial catalogue cannot be used safely."""


# Fail closed: an offer is recommended only after it has been accepted for the
# RDC commercial scope. Global portfolios and local-looking pages are not
# sufficient proof of current commercial availability.
RDC_COMMERCIAL_OFFER_IDS = frozenset({
    "liaison_specialisee_vpn",
    "business_sd_wan",
    "liaison_specialisee_internet",
    "api_orange_money",
    "api_sms",
    "bulk_sms_messaging_pro",
    "numero_vert",
    "essentiel_m2m",
    "business_gfu",
    "business_flex",
    "microsoft_365",
    "microsoft_365_entreprise",
    "hebergement_datacenter",
})

NON_LOCAL_AVAILABILITY = frozenset({"to_confirm", "unavailable", "not_available"})


@dataclass(frozen=True)
class LeadEvidence:
    evidence_id: int
    title: str
    publisher: str
    relationship: str
    excerpt: str


@dataclass(frozen=True)
class Offer:
    service_id: str
    name: str
    category: str
    description: str
    need_keywords: tuple[str, ...]
    sectors: tuple[str, ...]
    required_profile_fields: tuple[str, ...]
    rdc_availability: str


JOURNEYS: tuple[dict[str, Any], ...] = (
    {
        "journey_id": "multisite_network",
        "title": "Réseau multi-sites",
        "description": "Relier des agences, bureaux, dépôts ou sites distants.",
        "offer_ids": (
            "liaison_specialisee_vpn",
            "business_sd_wan",
            "liaison_specialisee_internet",
        ),
        "signals": (
            {
                "signal_id": "multiple_locations",
                "label": "Plusieurs implantations ou sites opérationnels",
                "keywords": (
                    "plusieurs agences", "nos agences", "succursales", "bureaux régionaux",
                    "sites distants", "réseau multisite", "multi-site", "entrepôts", "dépôts",
                    "implantations", "présence nationale", "présent à kinshasa", "présent à lubumbashi",
                ),
            },
        ),
        "sector_terms": (),
        "missing_information": "Nombre de sites, villes concernées, connectivité actuelle et niveau de disponibilité attendu.",
        "next_question": "Combien de sites doivent échanger des données et quels flux sont critiques entre eux ?",
        "next_action": "Confirmer les sites et la couverture avant de préparer une proposition réseau.",
    },
    {
        "journey_id": "payments_customer_communication",
        "title": "Paiement et communication client",
        "description": "Encaissement numérique, notifications et relation client.",
        "offer_ids": (
            "api_orange_money",
            "api_sms",
            "bulk_sms_messaging_pro",
            "numero_vert",
        ),
        "signals": (
            {
                "signal_id": "digital_sales",
                "label": "Parcours de vente ou paiement numérique",
                "keywords": (
                    "e-commerce", "commerce en ligne", "boutique en ligne", "commande en ligne",
                    "paiement en ligne", "paiement mobile", "mobile money", "encaissement numérique",
                    "application mobile", "plateforme numérique", "réservation en ligne",
                ),
            },
            {
                "signal_id": "customer_communication",
                "label": "Communication régulière avec des clients ou bénéficiaires",
                "keywords": (
                    "service client", "centre d'appel", "centre de contact", "hotline", "numéro vert",
                    "notification sms", "sms transactionnel", "campagne sms", "alerte client",
                    "suivi de commande", "livraison à domicile",
                ),
            },
        ),
        "sector_terms": (
            "commerce", "retail", "vente", "education", "éducation", "fintech",
            "technologie", "services numériques", "e-commerce",
        ),
        "missing_information": "Canaux actuels, volumes de transactions ou messages, intégrations disponibles et parcours client prioritaire.",
        "next_question": "Comment l’entreprise encaisse-t-elle et informe-t-elle ses clients aujourd’hui ?",
        "next_action": "Identifier le parcours client à améliorer avant de sélectionner l’API ou le canal adapté.",
    },
    {
        "journey_id": "mobility_m2m",
        "title": "Mobilité et M2M",
        "description": "Connecter des équipes terrain, véhicules, machines ou équipements.",
        "offer_ids": (
            "essentiel_m2m",
            "business_gfu",
            "business_flex",
        ),
        "signals": (
            {
                "signal_id": "fleet_field_operations",
                "label": "Flotte, logistique ou opérations de terrain",
                "keywords": (
                    "flotte de véhicules", "parc automobile", "véhicules", "camions", "engins",
                    "transport routier", "transport et logistique", "livraison", "distribution",
                    "équipes terrain", "agents terrain", "sites miniers", "opérations minières",
                ),
            },
            {
                "signal_id": "connected_equipment",
                "label": "Machines ou équipements susceptibles d’être connectés",
                "keywords": (
                    "équipements connectés", "objets connectés", "télémétrie", "suivi à distance",
                    "machines", "capteurs", "compteurs", "géolocalisation", "tracking",
                    "maintenance à distance",
                ),
            },
        ),
        "sector_terms": (
            "transport", "logistique", "industrie", "industriel", "énergie", "energie",
            "agriculture", "mines", "minier", "livraison", "distribution",
        ),
        "missing_information": "Nombre de lignes, véhicules ou équipements, zones d’opération et besoin de suivi ou de télémétrie.",
        "next_question": "Combien d’équipes, véhicules ou équipements opèrent hors bureau et que faut-il suivre à distance ?",
        "next_action": "Quantifier la flotte ou les équipements et vérifier les zones de couverture.",
    },
    {
        "journey_id": "collaboration_productivity",
        "title": "Collaboration et productivité",
        "description": "Messagerie professionnelle, travail hybride et outils collaboratifs.",
        "offer_ids": (
            "microsoft_365",
            "microsoft_365_entreprise",
        ),
        "signals": (
            {
                "signal_id": "collaboration_tools",
                "label": "Usage ou projet d’outils collaboratifs",
                "keywords": (
                    "microsoft 365", "office 365", "microsoft teams", "sharepoint", "onedrive",
                    "messagerie professionnelle", "email professionnel", "outils collaboratifs",
                    "suite collaborative", "visioconférence", "travail hybride", "télétravail",
                ),
            },
            {
                "signal_id": "distributed_workforce",
                "label": "Équipes distribuées ou travaillant à distance",
                "keywords": (
                    "équipes distribuées", "collaborateurs à distance", "travail à distance",
                    "bureaux distants", "équipes hybrides", "réunions à distance",
                ),
            },
        ),
        "sector_terms": (),
        "missing_information": "Nombre d’utilisateurs, outils actuels, domaine de messagerie, besoins de collaboration et exigences de sécurité.",
        "next_question": "Combien de collaborateurs utilisent la messagerie et quels outils partagent-ils entre bureaux ou à distance ?",
        "next_action": "Cartographier les utilisateurs et les licences actuelles avant de proposer une formule Microsoft 365.",
    },
    {
        "journey_id": "cybersecurity",
        "title": "Cybersécurité",
        "description": "Évaluer et protéger les applications, postes, serveurs et opérations numériques.",
        "offer_ids": (
            "cyber_diagnostic",
            "pentest",
            "micro_soc",
        ),
        "signals": (
            {
                "signal_id": "digital_exposure",
                "label": "Application ou service numérique exposé",
                "keywords": (
                    "application mobile", "plateforme numérique", "portail client", "espace client",
                    "site transactionnel", "e-commerce", "services en ligne", "api publique",
                    "application web", "paiement en ligne",
                ),
            },
            {
                "signal_id": "security_need",
                "label": "Enjeu public de sécurité, conformité ou résilience",
                "keywords": (
                    "cybersécurité", "cyberattaque", "incident de sécurité", "audit de sécurité",
                    "test d'intrusion", "vulnérabilités", "protection des données", "iso 27001",
                    "centre opérationnel de sécurité", "soc", "réponse à incident",
                ),
            },
        ),
        "sector_terms": (
            "banque", "finance", "fintech", "assurance", "santé", "sante", "gouvernement",
            "administration", "technologie", "télécommunication", "energie", "énergie", "minier",
        ),
        "missing_information": "Actifs exposés, incidents récents, exigences réglementaires, mesures actuelles et périmètre à évaluer.",
        "next_question": "Quels systèmes ou applications sont les plus critiques et comment leur sécurité est-elle contrôlée aujourd’hui ?",
        "next_action": "Identifier le périmètre critique avant d’orienter vers un diagnostic, un PenTest ou une supervision.",
    },
    {
        "journey_id": "cloud_datacenter_continuity",
        "title": "Datacenter et continuité",
        "description": "Héberger, sauvegarder et rendre les infrastructures plus résilientes.",
        "offer_ids": (
            "hebergement_datacenter",
            "global_cloud_portfolio",
        ),
        "signals": (
            {
                "signal_id": "it_infrastructure",
                "label": "Infrastructure serveur ou salle informatique",
                "keywords": (
                    "serveurs", "serveur d'entreprise", "salle informatique", "centre de données",
                    "data center", "datacenter", "infrastructure it", "infrastructure informatique",
                    "hébergement de données", "colocation", "rack",
                ),
            },
            {
                "signal_id": "cloud_continuity",
                "label": "Projet cloud, sauvegarde ou continuité d’activité",
                "keywords": (
                    "migration cloud", "cloud hybride", "cloud privé", "cloud public", "multicloud",
                    "infrastructure cloud", "sauvegarde cloud", "reprise après sinistre",
                    "disaster recovery", "plan de continuité", "continuité d'activité",
                ),
            },
        ),
        "sector_terms": (),
        "missing_information": "Applications hébergées, volumes, disponibilité attendue, sauvegardes actuelles, résidence des données et plan de reprise.",
        "next_question": "Où sont hébergées les applications critiques et comment l’activité reprend-elle après une panne majeure ?",
        "next_action": "Cartographier les applications, les données et les objectifs de reprise avant de choisir l’hébergement.",
    },
)


def _text_values(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def load_offer_catalog(path: str | Path | None = None) -> dict[str, Any]:
    catalogue_path = Path(path or settings.ONBORA_OFFER_CATALOG_PATH)
    try:
        payload = json.loads(catalogue_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LeadQualificationError("Le catalogue Orange configuré est introuvable ou illisible.") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("services"), list):
        raise LeadQualificationError("Le catalogue Orange ne contient pas de liste de services valide.")
    return payload


def _offers_by_id(payload: dict[str, Any]) -> dict[str, Offer]:
    result: dict[str, Offer] = {}
    for item in payload.get("services", []):
        if not isinstance(item, dict):
            continue
        service_id = str(item.get("service_id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not service_id or not name:
            continue
        availability = str(item.get("rdc_availability") or "").strip().casefold()
        portfolio_scope = str(item.get("portfolio_scope") or "").strip().casefold()
        if (
            service_id not in RDC_COMMERCIAL_OFFER_IDS
            or availability in NON_LOCAL_AVAILABILITY
            or portfolio_scope == "international"
        ):
            continue
        match = item.get("match") if isinstance(item.get("match"), dict) else {}
        result[service_id] = Offer(
            service_id=service_id,
            name=name[:500],
            category=str(item.get("category") or "Autre")[:180],
            description=str(item.get("description") or "")[:1600],
            need_keywords=_text_values(match.get("need_keywords")),
            sectors=_text_values(match.get("sectors")),
            required_profile_fields=_text_values(match.get("required_profile_fields")),
            rdc_availability="available",
        )
    return result


def available_rdc_offer_ids(catalog_payload: dict[str, Any] | None = None) -> frozenset[str]:
    """Return the fail-closed set of catalogue offers approved for RDC."""
    payload = catalog_payload or load_offer_catalog()
    return frozenset(_offers_by_id(payload))


def active_rdc_journey_ids(catalog_payload: dict[str, Any] | None = None) -> frozenset[str]:
    offer_ids = available_rdc_offer_ids(catalog_payload)
    return frozenset(
        journey["journey_id"]
        for journey in JOURNEYS
        if any(offer_id in offer_ids for offer_id in journey["offer_ids"])
    )


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = normalize(phrase)
    return bool(normalized_phrase and normalized_phrase in text)


def _matching_evidence(
    evidence: list[LeadEvidence], keywords: Iterable[str]
) -> tuple[list[int], list[str]]:
    evidence_ids: list[int] = []
    matched_keywords: list[str] = []
    for item in evidence:
        searchable = normalize(f"{item.title}\n{item.excerpt}")
        item_matches = [keyword for keyword in keywords if _contains_phrase(searchable, keyword)]
        if not item_matches:
            continue
        evidence_ids.append(item.evidence_id)
        for keyword in item_matches:
            if keyword not in matched_keywords:
                matched_keywords.append(keyword)
    return evidence_ids, matched_keywords


def _offer_rank(offer: Offer, company: CompanySeed, evidence_text: str) -> tuple[int, str]:
    keyword_matches = sum(_contains_phrase(evidence_text, keyword) for keyword in offer.need_keywords)
    sector_text = normalize(company.sector)
    sector_matches = sum(_contains_phrase(sector_text, sector) for sector in offer.sectors)
    return keyword_matches * 3 + sector_matches * 2, offer.service_id


def build_lead_qualification(
    company: CompanySeed,
    evidence: Iterable[LeadEvidence],
    identity_status: str,
    *,
    catalog_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build conservative, evidence-linked recommendations for three journeys."""
    try:
        payload = catalog_payload or load_offer_catalog()
        offers_by_id = _offers_by_id(payload)
    except LeadQualificationError as error:
        return {"status": "unavailable", "message": str(error)}

    evidence_list = list(evidence)
    evidence_text = normalize("\n".join(f"{item.title}\n{item.excerpt}" for item in evidence_list))
    evidence_by_id = {item.evidence_id: item for item in evidence_list}
    journeys: list[dict[str, Any]] = []

    for journey in JOURNEYS:
        journey_offer_ids = [offer_id for offer_id in journey["offer_ids"] if offer_id in offers_by_id]
        if not journey_offer_ids:
            continue
        signals = []
        journey_evidence_ids: list[int] = []
        for signal in journey["signals"]:
            evidence_ids, matched_keywords = _matching_evidence(evidence_list, signal["keywords"])
            if not evidence_ids:
                continue
            signals.append({
                "signal_id": signal["signal_id"],
                "label": signal["label"],
                "evidence_ids": evidence_ids,
                "matched_terms": matched_keywords[:5],
            })
            for evidence_id in evidence_ids:
                if evidence_id not in journey_evidence_ids:
                    journey_evidence_ids.append(evidence_id)

        sector_fit = any(_contains_phrase(normalize(company.sector), term) for term in journey["sector_terms"])
        publishers = {
            evidence_by_id[evidence_id].publisher
            for evidence_id in journey_evidence_ids
            if evidence_by_id[evidence_id].publisher
        }
        independent_publishers = {
            evidence_by_id[evidence_id].publisher
            for evidence_id in journey_evidence_ids
            if evidence_by_id[evidence_id].publisher
            and evidence_by_id[evidence_id].relationship == "independent"
        }

        if identity_status == "not_found":
            verdict = "non_qualifiable"
            confidence = "faible"
            reason = "L’identité de l’entreprise n’a pas été reliée à une preuve exploitable."
        elif journey_evidence_ids and len(independent_publishers) >= 2:
            verdict = "prioritaire"
            confidence = "élevé" if identity_status == "confirmed" else "moyen"
            reason = f"{len(independent_publishers)} sources indépendantes montrent des signaux compatibles avec ce parcours."
        elif journey_evidence_ids:
            verdict = "a_explorer"
            confidence = "moyen" if identity_status in {"confirmed", "probable"} else "faible"
            reason = "Un signal public compatible a été détecté, mais il doit être confirmé avec l’entreprise."
        elif sector_fit:
            verdict = "a_explorer"
            confidence = "faible"
            reason = "L’activité ARSP correspond au parcours, mais aucune preuve publique directe du besoin n’a encore été trouvée."
        else:
            verdict = "non_qualifiable"
            confidence = "faible"
            reason = "Les preuves disponibles ne montrent pas encore de signal commercial pour ce parcours."

        candidate_offers = (
            [offers_by_id[offer_id] for offer_id in journey_offer_ids]
            if verdict != "non_qualifiable" else []
        )
        candidate_offers.sort(key=lambda offer: (-_offer_rank(offer, company, evidence_text)[0], offer.service_id))
        offer_payload = [
            {
                "service_id": offer.service_id,
                "name": offer.name,
                "category": offer.category,
                "rdc_availability": offer.rdc_availability,
                "market": "RDC",
                "required_profile_fields": list(offer.required_profile_fields),
            }
            for offer in candidate_offers[:3]
        ]

        journeys.append({
            "journey_id": journey["journey_id"],
            "title": journey["title"],
            "description": journey["description"],
            "verdict": verdict,
            "verdict_label": {
                "prioritaire": "Prioritaire",
                "a_explorer": "À explorer",
                "non_qualifiable": "Non qualifiable",
            }[verdict],
            "confidence": confidence,
            "reason": reason,
            "signals": signals,
            "evidence_ids": journey_evidence_ids,
            "sector_fit": sector_fit,
            "offers": offer_payload,
            "missing_information": journey["missing_information"],
            "next_question": journey["next_question"],
            "next_action": journey["next_action"],
            "publisher_count": len(publishers),
        })

    verdict_order = {"prioritaire": 0, "a_explorer": 1, "non_qualifiable": 2}
    journeys.sort(key=lambda item: (verdict_order.get(item["verdict"], 9), item["title"]))
    return {
        "status": "complete",
        "catalog_version": str(payload.get("catalog_version") or payload.get("schema_version") or "non versionné")[:120],
        "catalog_status": str(payload.get("status") or "unknown")[:32],
        "market": "RDC",
        "journeys": journeys,
    }
