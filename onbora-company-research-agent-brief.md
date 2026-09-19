# Brief de découverte — Onbora Company Research Agent

<!-- brainstorm-section: discovery-verdict -->
## Discovery Verdict

- **Direction recommandée :** construire et tester un agent de collecte d’informations publiques sur une entreprise donnée, avant toute automatisation à grande échelle.
- **Utilisateur et résultat :** un KAM saisit une entreprise de la base ARSP et obtient une fiche enrichie, sourcée et explicite sur ses limites.
- **Pourquoi :** la valeur à démontrer maintenant est la qualité de la recherche, du recoupement et de la restitution. Ni le scoring commercial, ni le matching d’offres ne sont encore nécessaires.
- **Hypothèse la plus risquée :** les entreprises ayant une empreinte publique donnent assez de sources cohérentes pour produire une fiche utile.
- **Prochaine validation :** tester le même protocole sur une entreprise à forte empreinte, une à empreinte partielle, puis une presque invisible.
- **À décider maintenant :** le contrat de sortie de la fiche et les règles de confirmation d’identité.
- **Peut attendre :** traitement batch, scoring d’opportunité, recommandations Orange, CRM et automatisation de prospection.
- **Confiance :** moyenne. Un premier test a démontré des traces exploitables mais aussi des contradictions d’adresse.

<!-- brainstorm-section: mandate-and-horizon -->
## Mandat et horizon

- **Résultat attendu :** un protocole de recherche qui servira de base à l’architecture technique future.
- **Périmètre :** recherche sur une entreprise à la fois, à partir des données ARSP et de sources publiques en ligne.
- **Hors périmètre :** qualification commerciale, score, recommandation de produit, contact automatisé, enrichissement de toute la base.
- **Horizon de décision :** après 1 à 3 recherches réelles et évaluées manuellement.

<!-- brainstorm-section: evidence-and-assumptions -->
## Éléments connus, hypothèses et inconnues

| Élément | Type | Confiance | Impact si faux | Source ou validation |
|---|---|---:|---|---|
| La base ARSP contient le nom, RCCM, activité, province, adresse et coordonnées. | Fait | Élevée | Moyen | `liste_entreprises_arsp.xlsx` |
| Certaines coordonnées et identifiants sont dupliqués ou mal formatés. | Fait | Élevée | Élevé | Audit de la base ARSP |
| Des entreprises peuvent être documentées sans site officiel. | Fait observé | Élevée | Moyen | Test de recherche initial |
| Les traces publiques seront assez cohérentes pour confirmer l’identité d’une entreprise. | Hypothèse | Moyenne | Élevé | Tests sur 3 profils distincts |
| Une fiche enrichie sera utile à un KAM. | Hypothèse | Moyenne | Élevé | Relecture KAM après chaque test |

<!-- brainstorm-section: problem-and-opportunity -->
## Problème et opportunité

- **Situation :** un KAM possède un nom d’entreprise et un RCCM ARSP, mais manque de contexte fiable avant de contacter ou préparer un rendez-vous.
- **Progression recherchée :** transformer des traces publiques dispersées en une fiche d’entreprise vérifiable.
- **Alternative actuelle :** recherches manuelles, résultats non structurés et risque de confondre des entreprises aux noms proches.
- **Friction :** les sources sont inégales, parfois contradictoires, et une entreprise peut être présente sur les réseaux sans posséder de site.
- **Énoncé falsifiable :** pour les entreprises ayant des traces publiques recoupables, l’agent peut produire une fiche utile sans introduire de faits importants non sourcés.

<!-- brainstorm-section: actors-and-stakeholders -->
## Acteurs

| Acteur | Rôle | Résultat souhaité | Frein potentiel |
|---|---|---|---|
| KAM | Utilisateur et validateur | Comprendre rapidement un compte | Fiche longue, vague ou non fiable |
| Onbora | Opérateur du système | Produire une recherche traçable | Coût, qualité et identité ambiguë |
| Entreprise recherchée | Sujet de la recherche | Représentation fidèle | Confusion, données anciennes ou personnelles |

<!-- brainstorm-section: goals-and-non-goals -->
## Objectifs et exclusions

### Objectifs

- Confirmer ou signaler l’ambiguïté de l’identité d’une entreprise.
- Recueillir des faits publics utiles : activité réelle, présence, implantations, actualités et preuves de présence numérique.
- Associer chaque fait à une URL, une date de collecte et une source.
- Détecter et afficher les contradictions au lieu de les masquer.

### Exclusions

- Ne pas déduire un besoin commercial ou une offre à vendre.
- Ne pas contacter l’entreprise.
- Ne pas inventer les champs non trouvés.
- Ne pas chercher ou exploiter les données personnelles de dirigeants ou salariés.

<!-- brainstorm-section: option-portfolio -->
## Direction retenue

### Agent de recherche à la demande

- **Entrée :** dénomination légale, nom commercial, RCCM, province, activité, adresse et coordonnées ARSP.
- **Mécanisme :** lancer des requêtes ciblées, collecter les preuves, rapprocher les traces et générer une fiche de recherche.
- **Pourquoi cette direction :** elle permet de tester la valeur et la fiabilité avant d’investir dans le batch ou dans des modèles de scoring.
- **Test le moins coûteux :** trois recherches manuelles assistées par agent, puis revue ligne par ligne.

<!-- brainstorm-section: comparison-and-recommendation -->
## Recommandation et compromis

La recherche à la demande est retenue car elle isole l’incertitude principale : la capacité à trouver et vérifier des informations. Le compromis accepté est l’absence de couverture immédiate de la base entière.

Le filtre d’éligibilité n’est pas « site officiel obligatoire ». Une entreprise est éligible lorsqu’elle a une empreinte publique recoupable : site, Google Maps, Facebook, Instagram, TikTok, LinkedIn, presse, partenaires, appels d’offres, événements ou annuaires sectoriels.

### Concept d’outillage pour le prototype

Le prototype doit privilégier des composants sans compte externe et sans connexion aux réseaux sociaux :

```text
SearXNG local : recherche web multi-moteurs
        ↓
URLs publiques trouvées
        ↓
Trafilatura : extraction locale du texte et des métadonnées
        ↓
preuves conservées pour la fiche Onbora
```

Ce choix est une hypothèse de prototype, non une architecture définitive. Les services de recherche payants ou les connecteurs sociaux connectés ne seront évalués qu’après les premiers tests. Les réseaux sociaux publics restent des sources possibles, mais aucune connexion Facebook, Instagram, LinkedIn ou TikTok n’est requise dans le premier périmètre.

<!-- brainstorm-section: first-learning-scope -->
## Premier périmètre d’apprentissage

- **Véhicule :** recherche assistée par agent, avec validation humaine.
- **Déclencheur :** un utilisateur choisit une entreprise de la base ARSP jugée visible en ligne.
- **Promesse :** obtenir une fiche courte, structurée, vérifiable et honnête sur les informations absentes ou ambiguës.
- **Parcours critique :** saisie de l’entreprise → recherche multi-sources → recoupement d’identité → faits sourcés → fiche → revue humaine.
- **Capacités minimales :** génération de requêtes, collecte de résultats, extraction de faits, rapprochement, journal des sources et génération de fiche.
- **Concept technique provisoire :** SearXNG local pour découvrir les URLs et Trafilatura pour extraire le contenu des pages publiques.
- **Opérations manuelles :** choix des cas et contrôle des fiches initiales.
- **Exclusions explicites :** traitement automatique de milliers de lignes, monitoring continu, CRM, outreach et recommandation commerciale.
- **Signal de réussite :** le KAM confirme que la fiche apporte des informations utiles et qu’aucun fait important n’est non sourcé.
- **Signal d’arrêt ou pivot :** les sources ne permettent pas de distinguer de manière fiable les entreprises ou les fiches restent trop pauvres malgré des traces apparentes.

<!-- brainstorm-section: validation-backlog -->
## Backlog de validation

| Priorité | Hypothèse | Test | Règle de décision |
|---:|---|---|---|
| 1 | Les requêtes basées sur nom, RCCM et localisation identifient la bonne entreprise. | Tester sur une entreprise à nom distinctif. | Continuer si les sources concordent sur au moins deux attributs fiables. |
| 2 | Les sources non-site apportent de la valeur. | Tester une entreprise documentée via réseaux, annuaires ou presse. | Conserver ces sources si elles produisent des faits recoupables. |
| 3 | L’agent gère les contradictions sans halluciner. | Tester une entreprise avec adresses ou contacts divergents. | Continuer si chaque divergence est affichée comme telle. |
| 4 | La fiche est utile au KAM. | Faire relire les trois fiches. | Élargir seulement si les KAM jugent les résultats actionnables et fiables. |

<!-- brainstorm-section: risks-and-safeguards -->
## Règles de preuve et garde-fous

| Risque | Garde-fou |
|---|---|
| Mauvaise entreprise associée à une trace web | Exiger au minimum deux éléments concordants : RCCM, ville, téléphone, adresse, secteur, domaine ou nom commercial. |
| Information ancienne ou contradictoire | Conserver la date, la source et afficher les contradictions. |
| Contenu social non officiel | Le marquer « probable » tant qu’un élément d’identité ne le relie pas à l’entreprise ARSP. |
| Hallucination | Tout fait important doit avoir une source. Sinon : « non trouvé » ou « à confirmer ». |
| Contact personnel confondu avec contact corporate | Conserver l’origine des coordonnées et ne pas déclencher de prospection. |

<!-- brainstorm-section: discovery-stress-test -->
## Test de robustesse

- **Pourquoi cela pourrait ne pas suffire :** de nombreuses entreprises peuvent avoir une présence publique trop faible, ancienne ou ambiguë.
- **Hypothèse la plus dangereuse :** qu’un nom commercial ou une page sociale représente automatiquement l’entité RCCM visée.
- **Alternative la moins chère :** recherche manuelle Google par le KAM. L’agent doit donc gagner sur la structure, le recoupement et la traçabilité, pas seulement sur la vitesse.
- **Échec principal :** produire une fiche convaincante mais erronée. La traçabilité et l’affichage de l’incertitude priment sur la complétude.

<!-- brainstorm-section: decisions-and-unknowns -->
## Décisions et inconnues

- **Décidé :** commencer par 1 à 3 entreprises visibles et une recherche à la demande.
- **Décidé :** ne pas inclure, à ce stade, de scoring, de recommandations d’offres ou d’automatisation de prospection.
- **Décidé :** le site web enrichit fortement le brief mais n’est pas une condition d’éligibilité.
- **Décidé pour le prototype :** privilégier SearXNG local et Trafilatura afin d’éviter les comptes et les dépendances payantes au démarrage.
- **Différé :** APIs commerciales de recherche et connecteurs sociaux avec session connectée.
- **Inconnu :** quels types de sources donnent les faits les plus fiables selon le secteur.
- **Inconnu :** quel niveau d’information un KAM considère comme suffisant pour une fiche utile.

<!-- brainstorm-section: handoff-for-prd -->
## Handoff pour l’architecture

### Flux fonctionnel minimal

```text
ARSP company seed
       ↓
Research request
       ↓
Query planner
       ↓
Public-source collection
       ↓
Evidence store
       ↓
Entity resolution and contradiction detection
       ↓
Structured company brief
       ↓
Human review
```

### Contrat d’entrée

```json
{
  "legal_name": "…",
  "trade_name": "…",
  "rccm": "…",
  "province": "…",
  "activity_arsp": "…",
  "address_arsp": "…"
}
```

### Contrat de sortie

```json
{
  "identity_status": "confirmed | probable | ambiguous | not_found",
  "facts": [
    {
      "field": "activity | location | website | social_presence | news | contact",
      "value": "…",
      "status": "confirmed | probable | conflicting",
      "evidence": [{ "url": "…", "collected_at": "…", "source_type": "…" }]
    }
  ],
  "contradictions": [],
  "not_found": [],
  "research_log": []
}
```

### Contraintes d’architecture à préserver

- La collecte de preuves doit être séparée de l’IA qui synthétise la fiche.
- Les preuves brutes, leur URL et leur date doivent être stockées avant toute interprétation.
- L’agent ne doit jamais transformer une supposition en fait.
- Chaque exécution doit être rejouable et auditable.
- Le passage à grande échelle ne sera envisagé qu’après validation humaine du protocole.
