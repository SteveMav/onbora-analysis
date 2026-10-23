"""Useful company facts, with public evidence and registry declarations separated."""

from __future__ import annotations

from .text_utils import clean_excel_text


PROFILE_FIELDS = {
    "description": "Description de l’entreprise",
    "activity": "Activité",
    "address": "Adresse / siège",
    "services": "Produits et services",
    "locations": "Implantations et zone d’intervention",
    "contacts": "Contacts professionnels",
    "highlights": "Autres informations utiles",
}

PROFILE_INSTRUCTIONS = """
Produis une fiche utile pour comprendre l'entreprise et préparer un échange.
Dans company_profile, classe les faits explicitement présents dans les preuves :
- description : présentation concrète de ce que fait l'entreprise, pour qui ;
- activity : activités principales et secondaires réellement décrites ;
- address : adresse précise et siège, sans transformer une province en adresse ;
- services : produits, prestations, spécialités ;
- locations : agences, bureaux, sites et zones d'intervention ;
- contacts : site, email et téléphone professionnels publics de l'entreprise ;
- highlights : clients, partenaires, projets, année de création, taille ou
  actualités datées, seulement si ces informations sont explicitement sourcées.
Chaque rubrique contient un tableau de zéro à trois affirmations (text,
evidence_ids). Une rubrique inconnue est un tableau vide : ne la devine pas et
signale les lacunes importantes dans gaps. N'utilise pas les seules données ARSP
du contexte comme preuve publique : l'application les affiche séparément.
Ne collecte pas de coordonnées personnelles de salariés ou dirigeants.
overview présente l'entreprise en deux ou trois phrases concrètes. Réserve
key_facts aux faits utiles supplémentaires, sans répéter toutes les rubriques.
Conserve les adresses ou activités contradictoires et explique-les dans
contradictions. Une source « À vérifier » exige une attribution prudente au
profil concerné, sans affirmer que son identité juridique est confirmée.
""".strip()


def _declared_text(value) -> str:
    text = clean_excel_text(value)
    if text.casefold().strip(" .-–") in {
        "", "non spécifié", "non specifie", "non renseigné", "non renseigne",
        "non renseignée", "non renseignee", "inconnu", "néant", "neant",
        "n/a", "na", "null", "none", "à préciser", "a preciser",
    }:
        return ""
    return text


def company_profile_view(summary: dict, seed: dict, evidence_links: list) -> dict:
    """Render old and new runs without inventing missing facts or source URLs."""
    evidence_by_id = {
        link.evidence_id: link for link in evidence_links
        if link.verdict in {"Pertinente", "À vérifier"}
    }
    profile = summary.get("company_profile", {}) if summary.get("status") == "complete" else {}
    if not isinstance(profile, dict):
        profile = {}
    declared = {
        "activity": [_declared_text(seed.get("activity_arsp"))],
        "address": [_declared_text(seed.get("address_arsp"))],
        "contacts": [
            f"{label} : {text}" for key, label in (("email_arsp", "Email"), ("phone_arsp", "Téléphone"))
            if (text := _declared_text(seed.get(key)))
        ],
    }
    fields = []
    for key, label in PROFILE_FIELDS.items():
        values = profile.get(key, [])
        # Historical summaries predate structured profiles; their cited overview
        # remains useful as a description, while all other fields stay explicit.
        if key == "description" and not profile:
            values = [summary.get("overview", {})] if summary.get("status") == "complete" else []
        items = []
        for value in values[:3] if isinstance(values, list) else []:
            if not isinstance(value, dict) or not isinstance(value.get("evidence_ids"), list):
                continue
            text = clean_excel_text(value.get("text"))[:1200]
            sources = []
            for evidence_id in value["evidence_ids"]:
                if type(evidence_id) is not int or evidence_id not in evidence_by_id:
                    continue
                link = evidence_by_id[evidence_id]
                if any(source["evidence_id"] == evidence_id for source in sources):
                    continue
                sources.append({
                    "evidence_id": evidence_id,
                    "title": link.evidence.title or link.evidence.publisher,
                    "publisher": link.evidence.publisher,
                    "url": link.evidence.observed_url,
                    "verdict": link.verdict,
                })
            if text and sources:
                items.append({
                    "text": text, "sources": sources,
                    "uncertain": all(source["verdict"] == "À vérifier" for source in sources),
                })
        declarations = [text for text in declared.get(key, []) if text]
        fields.append({"key": key, "label": label, "items": items, "declared": declarations})
    identifiers = [
        {"label": label, "text": text}
        for key, label in (("trade_name", "Nom commercial"), ("province", "Province"),
                           ("rccm", "RCCM"), ("tax_number", "Numéro fiscal"))
        if (text := _declared_text(seed.get(key)))
    ]
    return {"fields": fields, "identifiers": identifiers}
