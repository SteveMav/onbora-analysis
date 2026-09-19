from django import forms

from .models import HumanBenchmarkCase


class HumanBenchmarkCaseForm(forms.ModelForm):
    class Meta:
        model = HumanBenchmarkCase
        fields = [
            "source_potential",
            "identity_check",
            "system_verdict",
            "pages_reviewed",
            "useful_fact_count",
            "human_findings",
            "missed_information",
            "reviewer_notes",
        ]
        labels = {
            "source_potential": "Ce que les sources permettent à un humain de trouver",
            "identity_check": "Identité de l’entreprise",
            "system_verdict": "Utilité du résultat produit par Onbora",
            "pages_reviewed": "Pages vérifiées manuellement",
            "useful_fact_count": "Faits utiles trouvés par l’humain",
            "human_findings": "Informations utiles trouvées manuellement",
            "missed_information": "Informations présentes sur les pages mais manquées par Onbora",
            "reviewer_notes": "Notes ou problèmes observés",
        }
        help_texts = {
            "human_findings": "Une information par ligne, avec la source si possible.",
            "missed_information": "Laisse vide si Onbora n’a rien manqué d’important.",
        }
        widgets = {
            "pages_reviewed": forms.NumberInput(attrs={"min": 0, "max": 100}),
            "useful_fact_count": forms.NumberInput(attrs={"min": 0, "max": 100}),
            "human_findings": forms.Textarea(attrs={"rows": 4, "placeholder": "Ex. activité réelle, implantation, projet récent…"}),
            "missed_information": forms.Textarea(attrs={"rows": 4, "placeholder": "Copie ici les faits que le système aurait dû extraire…"}),
            "reviewer_notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Source bloquée, confusion d’identité, extrait incomplet…"}),
        }

    def clean(self):
        cleaned = super().clean()
        pages_reviewed = cleaned.get("pages_reviewed")
        useful_fact_count = cleaned.get("useful_fact_count")
        if pages_reviewed is not None and pages_reviewed > 100:
            self.add_error("pages_reviewed", "Le benchmark est limité à 100 pages par entreprise.")
        if useful_fact_count is not None and useful_fact_count > 100:
            self.add_error("useful_fact_count", "Le benchmark est limité à 100 faits par entreprise.")
        if (
            cleaned.get("source_potential") in {
                HumanBenchmarkCase.SourcePotential.LIMITED,
                HumanBenchmarkCase.SourcePotential.USEFUL,
            }
            and not (cleaned.get("human_findings") or "").strip()
        ):
            self.add_error("human_findings", "Décris au moins une information utile trouvée.")
        return cleaned
