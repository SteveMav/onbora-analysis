# Feature Product Requirements — Onbora Company Research Agent

<!-- prd-section: product-verdict -->
## Product Verdict

- **Décision produit :** construire un prototype contrôlé de recherche à la demande sur une entreprise ARSP, avec preuve conservée, résolution d’identité explicite et validation humaine obligatoire.
- **Acteur et résultat :** un KAM sélectionne une ligne ARSP et obtient une fiche courte qui distingue faits confirmés, éléments probables, contradictions et informations non trouvées.
- **Périmètre MVP :** une entreprise par exécution, trois profils de visibilité testés, sources publiques sans session sociale, sortie structurée et revue ligne par ligne.
- **Ambiguïté ou risque principal :** associer une trace publique à la mauvaise entité lorsqu’un nom, un RCCM, une adresse ou un contact est partagé, ancien ou mal formaté.
- **À décider maintenant :** utiliser le `Numéro Dossier` comme identifiant stable de la ligne source; appliquer les règles d’identité et de preuve définies dans ce PRD; interdire toute fiche présentée comme validée avant revue humaine.
- **Peut attendre :** traitement batch, CRM, scoring commercial, recommandations d’offres, prospection, connecteurs sociaux authentifiés et fournisseur de recherche payant.
- **Readiness :** `ready with assumptions` pour un prototype interne de 1 à 3 cas. Une décision de conservation des preuves est requise avant tout pilote élargi.
- **Confiance :** moyenne. Le brief est cohérent et le fichier ARSP confirme les problèmes de qualité de données, mais l’utilité KAM et la couverture web ne sont pas encore mesurées.

<!-- prd-section: feature-contract -->
## Feature Contract

### Objectif et justification

Permettre à un KAM de comprendre plus vite une entreprise ARSP à partir d’informations publiques, sans masquer l’incertitude ni introduire de fait important non sourcé. Le prototype doit d’abord démontrer la qualité de la résolution d’identité, du recoupement et de la restitution. Il ne doit pas prendre de décision commerciale.

### Déclencheur et résultat observable

- **Déclencheur :** un KAM autorisé choisit une ligne de la base ARSP et lance une recherche.
- **Alternative actuelle :** recherches web manuelles, non structurées et difficilement auditables.
- **Résultat attendu :** une fiche consultable, reliée à la ligne ARSP d’origine, dont chaque affirmation importante renvoie à une ou plusieurs preuves publiques datées.
- **Horizon de décision :** revue de trois cas réels — forte empreinte, empreinte partielle, empreinte quasi inexistante — avant toute décision d’industrialisation.

### Frontière produit

Le produit contrôle la sélection de l’entrée ARSP, le lancement et le suivi de la recherche, la conservation des preuves, la classification de l’identité et des faits, la génération de la fiche et la revue humaine. Il ne contrôle ni la disponibilité ni l’exactitude des sites tiers.

### Invariants

1. Aucun fait important ne peut apparaître sans preuve accessible dans la fiche.
2. Une absence de preuve devient `non trouvé` ou `à confirmer`, jamais une valeur inventée.
3. Les contradictions restent visibles jusqu’à leur résolution explicite.
4. Une source sociale ou un annuaire générique ne suffit pas, à lui seul, à confirmer l’identité.
5. Une fiche non revue ne peut pas être présentée comme validée par Onbora.
6. Les preuves collectées et leur provenance sont conservées séparément de la synthèse générée.
7. Le produit ne recherche pas, ne classe pas et n’expose pas de données personnelles sur des dirigeants ou salariés.
8. Le prototype n’envoie aucun message et ne déclenche aucune action externe envers l’entreprise recherchée.

### Terminologie normative

- **Attribut d’identité à forte spécificité :** RCCM exact, numéro d’impôt exact, adresse complète concordante, téléphone corporate exact, email ou domaine corporate relié à la dénomination.
- **Attribut d’identité de soutien :** dénomination ou nom commercial, province ou ville, secteur d’activité, implantation, variante orthographique.
- **Source indépendante :** éditeur ou domaine distinct qui ne republie pas manifestement la même donnée sans vérification.
- **Fait important :** toute valeur montrée dans les rubriques identité, activité, implantation, présence numérique, actualité ou contact corporate.
- **Preuve :** enregistrement comportant au minimum URL, titre ou origine, type de source, date de collecte, état d’accès et extrait court ou attribut directement pertinent.
- **Contradiction forte :** divergence portant sur un identifiant légal, une entité candidate, une adresse principale, un téléphone corporate ou un domaine officiel, et susceptible de changer l’entité associée.

### Règles de décision d’identité

| Statut | Règle produit |
|---|---|
| `confirmed` | Un identifiant légal exact et le nom concordent sur une source publique pertinente, **ou** au moins trois attributs concordent sur deux sources indépendantes, dont au moins un attribut à forte spécificité, sans contradiction forte non résolue. |
| `probable` | Au moins deux attributs concordent sur deux sources indépendantes, dont un attribut à forte spécificité, mais le seuil de confirmation n’est pas atteint. |
| `ambiguous` | Plusieurs entités restent plausibles, une contradiction forte n’est pas résolue, ou seules des correspondances faibles comme nom, secteur et ville sont disponibles. |
| `not_found` | Aucun candidat exploitable n’est trouvé après exécution du protocole minimal de recherche et consignation des catégories de sources tentées. |

Le statut le plus conservateur prévaut. Le KAM peut rejeter ou demander une révision, mais ne peut pas transformer manuellement `ambiguous` ou `not_found` en `confirmed` sans ajouter une preuve répondant aux règles ci-dessus.

### Règles de décision des faits

| Statut | Règle produit |
|---|---|
| `confirmed` | Le fait est directement publié par une source officielle reliée à l’entité confirmée, ou corroboré par au moins deux sources indépendantes. |
| `probable` | Le fait est directement déclaré par une seule source pertinente, ou sa source est reliée à une identité seulement probable. |
| `conflicting` | Deux preuves pertinentes présentent des valeurs incompatibles et aucune règle documentée ne permet de retenir l’une d’elles. |

Une inférence non déclarée explicitement par une source ne peut pas devenir un fait. Elle peut uniquement apparaître dans une note de limitation formulée comme hypothèse.

### Contrat de sortie minimal

```json
{
  "schema_version": "1.0",
  "request": {
    "request_id": "...",
    "source_record_id": "Numéro Dossier ARSP",
    "requested_by": "...",
    "requested_at": "date-heure avec fuseau",
    "input_snapshot": {
      "legal_name": "...",
      "trade_name": "...",
      "rccm": "...",
      "tax_number": "...",
      "province": "...",
      "activity_arsp": "...",
      "address_arsp": "...",
      "phone_arsp": "...",
      "email_arsp": "..."
    }
  },
  "run": {
    "state": "queued | researching | awaiting_review | reviewed | failed | cancelled",
    "coverage": "complete | partial",
    "started_at": "...",
    "completed_at": "...",
    "limitations": []
  },
  "identity": {
    "status": "confirmed | probable | ambiguous | not_found",
    "matched_name": "...",
    "matched_attributes": [],
    "candidate_entities": [],
    "rationale": "..."
  },
  "facts": [
    {
      "fact_id": "...",
      "field": "activity | location | website | social_presence | news | contact",
      "value": "...",
      "status": "confirmed | probable | conflicting",
      "as_of": "...",
      "evidence_ids": []
    }
  ],
  "evidence": [
    {
      "evidence_id": "...",
      "url": "...",
      "title": "...",
      "publisher": "...",
      "source_type": "official | registry | procurement | press | partner | social | directory | other",
      "relationship": "first_party | independent | discovery_only",
      "published_at": "...",
      "collected_at": "...",
      "access_status": "accessible | partial | unavailable",
      "relevant_excerpt": "..."
    }
  ],
  "contradictions": [],
  "not_found": [],
  "research_log": [],
  "review": {
    "status": "pending | accepted | revision_requested | rejected",
    "reviewed_by": "...",
    "reviewed_at": "...",
    "notes": "..."
  }
}
```

<!-- prd-section: evidence-and-assumptions -->
## Evidence and Assumptions

| ID | Énoncé | Type | Confiance | Impact si faux | Source ou validation |
|---|---|---|---|---|---|
| EVD-001 | Le fichier ARSP observé contient 11 991 lignes de données et 11 colonnes utiles au seed de recherche. | Fait observé | Élevée | Moyen | `liste_entreprises_arsp.xlsx`, feuille `Données`, audit du 13 septembre 2026. |
| EVD-002 | Le `Numéro Dossier` est renseigné et unique sur les 11 991 lignes observées. | Fait observé | Élevée | Élevé | Audit du fichier ARSP; à revalider à chaque nouvelle version importée. |
| EVD-003 | Le RCCM n’est pas une clé unique dans le fichier actuel : 101 groupes de doublons normalisés couvrent 208 lignes. | Fait observé | Élevée | Élevé | Audit du fichier ARSP. |
| EVD-004 | Les champs présentent des défauts de forme : espaces superflus ou multiples sur 1 017 dénominations, 412 RCCM, 1 222 adresses, 406 téléphones et 316 emails. | Fait observé | Élevée | Moyen | Audit normalisé du fichier ARSP. |
| EVD-005 | Des valeurs sont absentes : 13 adresses, 51 téléphones et 25 emails. | Fait observé | Élevée | Moyen | Audit du fichier ARSP. |
| EVD-006 | Une entreprise peut être documentée sans site officiel. | Rapporté / observé dans la découverte | Élevée | Moyen | Brief de découverte; à reproduire sur le cas d’empreinte partielle. |
| ASM-001 | Les sources publiques permettront une résolution d’identité suffisamment fiable sur au moins deux des trois profils testés. | Hypothèse | Moyenne | Élevé | Revue manuelle des trois cas et calcul de MET-001/MET-003. |
| ASM-002 | Une fiche courte, sourcée et explicite sur ses limites est utile à un KAM. | Hypothèse | Moyenne | Élevé | Évaluation KAM structurée après chaque recherche. |
| ASM-003 | Une interface interne en français répond au premier usage. | Hypothèse | Moyenne | Faible pour le prototype | Confirmer avec le KAM pilote avant élargissement. |
| DEC-001 | Le `Numéro Dossier` identifie la ligne source; le RCCM reste un attribut de rapprochement. | Décision | Élevée | Élevé | Justifiée par EVD-002 et EVD-003. |
| DEC-002 | Le prototype peut utiliser SearXNG local et Trafilatura, mais ces outils ne font pas partie du contrat produit. | Décision provisoire | Moyenne | Faible | À évaluer par l’architecture selon la couverture et la qualité mesurées. |
| UNK-001 | La durée acceptable d’une recherche et le niveau minimal d’information utile ne sont pas encore mesurés. | Inconnu | — | Moyen | MET-002, MET-005 et entretien KAM après chaque cas. |
| UNK-002 | La politique de conservation des preuves et journaux au-delà du test contrôlé n’est pas décidée. | Inconnu | — | Élevé pour un pilote élargi | Décision Product/Data/Legal avant élargissement. |

<!-- prd-section: actors-and-permissions -->
## Actors and Permissions

| Acteur | Relation à la ressource | Informations visibles | Actions autorisées | Comportement refusé ou soumis à validation |
|---|---|---|---|---|
| KAM demandeur | Créateur d’une demande interne | Seed ARSP, progression, fiche, preuves, contradictions, limites, décision de revue | Lancer une recherche unitaire, consulter, demander une révision, accepter ou rejeter la fiche, ajouter une note | Pas de modification silencieuse des preuves ou statuts calculés; pas de contact ou export de données personnelles. |
| KAM relecteur | Validateur humain; peut être le demandeur dans le prototype | Même visibilité que le demandeur | Vérifier chaque fait, qualifier l’utilité, accepter, rejeter ou demander une révision | Un passage à `confirmed` exige une nouvelle preuve conforme aux règles. |
| Opérateur Onbora | Opérateur du protocole et du support | Toutes les exécutions du prototype, journaux, erreurs et preuves | Relancer une collecte échouée, annuler une exécution, documenter une limitation, traiter une demande de correction ou suppression | Ne peut pas réécrire l’historique d’une preuve ou d’une revue; toute correction crée une nouvelle version auditée. |
| Entreprise recherchée | Sujet des données, sans accès au prototype | Aucune information interne | Aucun acte dans le prototype | Toute future demande d’accès, correction ou suppression suit une procédure Onbora à définir avant pilote élargi. |
| Système/source publique | Fournisseur externe non contrôlé | Uniquement la requête publique reçue selon son fonctionnement | Retourner, refuser ou interrompre l’accès | Aucun contournement d’authentification, paywall, restriction d’accès ou mécanisme anti-automatisation. |

Pour le prototype, l’accès est limité à des utilisateurs internes explicitement autorisés. Une matrice d’habilitation plus fine n’est pas requise avant l’élargissement.

<!-- prd-section: scope-and-priorities -->
## Scope and Priorities

| Élément | Priorité | Justification | Dépendances |
|---|---|---|---|
| Sélection d’une ligne ARSP par `Numéro Dossier` et capture immuable du seed | Must | Préserver l’identité de l’entrée malgré les doublons et corrections ultérieures | Fichier ARSP accessible et schéma reconnu |
| Validation et normalisation non destructive des champs d’entrée | Must | Éviter qu’un défaut de forme devienne une fausse divergence | Règles de normalisation journalisées |
| Recherche publique multi-source sur une seule entreprise | Must | Parcours critique et question d’apprentissage principale | Accès web public |
| Journal des requêtes, URLs tentées, erreurs et exclusions | Must | Audit, diagnostic de couverture et reproductibilité | Horodatage et identifiant d’exécution |
| Conservation de preuves minimales avant synthèse | Must | Garde-fou contre l’hallucination | Stockage contrôlé et politique provisoire |
| Résolution d’identité selon la table normative | Must | Empêcher la mauvaise association | Preuves et attributs normalisés |
| Classification des faits et contradictions | Must | Restitution honnête et vérifiable | Identité et provenance |
| Fiche courte lisible et contrat JSON versionné | Must | Utilité KAM et handoff technique stable | Schéma de sortie 1.0 |
| Revue humaine avec décision et commentaire | Must | Validation du protocole avant automatisation | KAM ou opérateur désigné |
| Gestion des erreurs, sources indisponibles et reprise | Must | Éviter une fiche faussement complète | État d’exécution et journal |
| Comparaison entre exécution initiale et réexécution | Should | Comprendre les changements de sources ou de règles | Versionnage des exécutions |
| Recherche sur une URL fournie manuellement par le KAM | Should | Récupération simple lorsqu’une source connue manque | Validation URL et règles de collecte |
| Export humain lisible de la fiche | Could | Faciliter le partage interne après validation | Décision de format |

### Won’t for now

- Traitement batch de la base ARSP; reconsidérer après le go du protocole et l’estimation du coût unitaire.
- Scoring d’opportunité, recommandation Orange, segmentation commerciale ou priorisation de comptes; reconsidérer après preuve d’une donnée fiable et utile.
- CRM, outreach, emails, appels ou automatisation de prospection; reconsidérer dans un produit séparé avec consentement et règles commerciales.
- Connexion authentifiée à Facebook, Instagram, LinkedIn, TikTok ou autre réseau; reconsidérer si la couverture publique est insuffisante et si les conditions d’usage le permettent.
- Surveillance continue et alertes; reconsidérer après validation du besoin de fraîcheur.
- Recherche de profils, noms, coordonnées personnelles ou données de dirigeants et salariés.
- Décision juridique sur l’entreprise, certification d’existence, KYC ou due diligence réglementaire.

<!-- prd-section: flows-states-errors -->
## Flows, States, and Errors

### JOURNEY-001 — Recherche et revue d’une entreprise

1. Le KAM choisit une ligne ARSP identifiée par `Numéro Dossier`.
2. Le produit affiche le seed brut et les avertissements de qualité détectés avant lancement.
3. Le KAM lance la demande. Le produit crée un `request_id`, fige le seed et passe l’exécution à `queued`.
4. Le produit refuse une seconde exécution active identique et ouvre l’exécution existante.
5. L’exécution passe à `researching`; le produit affiche la progression par étape sans promettre de complétude.
6. Les requêtes combinent nom, RCCM, localisation, activité et coordonnées disponibles. Chaque tentative est journalisée.
7. Chaque contenu pertinent est enregistré comme preuve avant extraction d’un fait.
8. Le produit rapproche les candidats, applique le statut d’identité le plus conservateur et détecte les contradictions.
9. Il génère la fiche et passe à `awaiting_review`, même si la couverture est `partial`, dès lors que les limites sont explicites.
10. Le KAM vérifie les faits et les preuves, note l’utilité, puis accepte, rejette ou demande une révision.
11. Le produit conserve la décision, l’auteur, l’heure et la version; l’exécution passe à `reviewed` après une décision finale `accepted` ou `rejected`.

### Parcours alternatifs, refus et récupération

- **Seed incomplet :** une recherche peut démarrer si `Numéro Dossier` et une dénomination sont présents. Les champs absents apparaissent comme limites d’entrée.
- **Doublon ou collision :** si plusieurs lignes ont le même RCCM ou nom, le produit affiche les lignes candidates; le `Numéro Dossier` choisi reste la source de vérité de la demande.
- **Identité insuffisante :** le produit produit une fiche `ambiguous` ou `not_found`; il ne rattache pas les faits d’un candidat incertain à l’entreprise ARSP.
- **Source inaccessible :** la tentative est marquée `unavailable`; la fiche passe à couverture `partial` si le reste du parcours peut aboutir.
- **Interruption :** les preuves déjà conservées et le journal restent attachés à l’exécution. Une reprise n’insère pas deux fois la même preuve URL/version.
- **Échec total :** l’exécution passe à `failed`, affiche l’étape fautive et permet une relance liée à la version précédente.
- **Annulation :** l’opérateur peut annuler une recherche active. Aucune nouvelle collecte n’est lancée; les éléments déjà collectés restent soumis à la politique de conservation.
- **Réexécution :** une nouvelle exécution crée une version liée; elle ne remplace ni la fiche ni la revue antérieure.
- **URL manuelle invalide ou interdite :** la source est refusée avec une raison compréhensible; aucun contournement n’est tenté.

### États et dimensions

| Dimension | Valeurs | Règle de transition |
|---|---|---|
| Exécution | `queued`, `researching`, `awaiting_review`, `reviewed`, `failed`, `cancelled` | Transitions auditables; `failed` et `cancelled` sont terminaux pour cette exécution; une reprise crée une exécution liée. |
| Couverture | `complete`, `partial` | `partial` dès qu’une catégorie requise n’a pas pu être tentée ou qu’une dépendance a échoué; ne signifie pas que l’identité est incorrecte. |
| Identité | `confirmed`, `probable`, `ambiguous`, `not_found` | Calculée selon les règles normatives; toute correction est versionnée. |
| Fait | `confirmed`, `probable`, `conflicting` | Calculé pour chaque fait et lié à ses preuves. |
| Revue | `pending`, `accepted`, `revision_requested`, `rejected` | `pending` jusqu’à action humaine; `revision_requested` renvoie vers une nouvelle exécution ou version de fiche. |

<!-- prd-section: requirements-and-acceptance -->
## Requirements and Acceptance Criteria

### FR-001 — Identifier et figer l’entrée ARSP

- **Priorité :** Must
- **Exigence :** lorsqu’un KAM sélectionne une entreprise, le produit doit identifier la ligne par `Numéro Dossier` et conserver un instantané immuable de tous les champs ARSP utilisés.
- **Rationale/source :** DEC-001; EVD-002; EVD-003.

#### Acceptance criteria

- **AC-FR-001-01 Primary:** étant donné une ligne valide, lorsque la recherche est lancée, alors la demande contient un `source_record_id`, un `request_id` et les valeurs brutes du seed.
- **AC-FR-001-02 Boundary:** étant donné deux lignes au même RCCM, lorsque l’une est choisie, alors leur `source_record_id` les distingue et le produit n’agrège pas leurs données.
- **AC-FR-001-03 Error:** si le numéro de dossier ou la dénomination manque, le lancement est refusé avec le champ requis indiqué.
- **AC-FR-001-04 Recovery:** si la base ARSP change après lancement, l’ancienne demande continue d’afficher l’instantané original.

### FR-002 — Normaliser sans altérer la provenance

- **Priorité :** Must
- **Exigence :** avant la recherche, le produit doit produire des variantes normalisées destinées au rapprochement tout en conservant les valeurs ARSP brutes.
- **Rationale/source :** EVD-004; éviter faux négatifs et fausses corrections.

#### Acceptance criteria

- **AC-FR-002-01 Primary:** les espaces de début/fin et espaces multiples peuvent être normalisés pour la recherche, tandis que la valeur originale reste visible.
- **AC-FR-002-02 Boundary:** un zéro initial de téléphone, la casse d’un email ou la ponctuation d’un RCCM ne sont pas supprimés de la valeur brute.
- **AC-FR-002-03 Error:** une valeur non interprétable est signalée comme telle et n’est pas remplacée par une valeur supposée.

### FR-003 — Garantir une exécution unitaire et idempotente

- **Priorité :** Must
- **Exigence :** lorsqu’une recherche est lancée, le produit doit créer une seule exécution active par ligne source et paramètres identiques, sans side effect externe.
- **Rationale/source :** périmètre MVP et auditabilité.

#### Acceptance criteria

- **AC-FR-003-01 Primary:** un lancement crée une exécution `queued` horodatée.
- **AC-FR-003-02 Duplicate:** une seconde soumission identique pendant l’exécution ouvre l’exécution active et n’en crée pas une autre.
- **AC-FR-003-03 Retry:** après `failed`, une relance crée un nouvel identifiant lié à l’exécution précédente.
- **AC-FR-003-04 Denied:** aucun lancement ne contacte l’entreprise ni ne publie d’information.

### FR-004 — Planifier et journaliser la recherche

- **Priorité :** Must
- **Exigence :** pour chaque exécution, le produit doit générer des requêtes ciblées à partir des attributs disponibles et consigner chaque requête, l’heure, le résultat et la raison d’une exclusion.
- **Rationale/source :** reproductibilité et diagnostic de couverture.

#### Acceptance criteria

- **AC-FR-004-01 Primary:** le journal montre quelles combinaisons de nom, RCCM, localisation, activité ou contact ont été tentées.
- **AC-FR-004-02 Missing input:** l’absence d’un attribut réduit les requêtes possibles mais ne génère jamais de valeur fictive.
- **AC-FR-004-03 Source class:** le protocole tente, lorsqu’elles existent, des sources officielles, indépendantes et de découverte; une catégorie non tentée est expliquée.
- **AC-FR-004-04 Privacy:** aucune requête ne cible le nom ou le profil personnel d’un dirigeant ou salarié.

### FR-005 — Respecter les limites d’accès public

- **Priorité :** Must
- **Exigence :** le produit doit collecter uniquement les contenus accessibles publiquement sans authentification et respecter tout refus d’accès observé.
- **Rationale/source :** périmètre, conditions d’usage et minimisation du risque.

#### Acceptance criteria

- **AC-FR-005-01 Primary:** une page publique accessible peut devenir une preuve.
- **AC-FR-005-02 Denied:** une page exigeant connexion, contournement de paywall ou mécanisme anti-bot est journalisée comme indisponible sans contournement.
- **AC-FR-005-03 Partial:** si une source échoue mais d’autres aboutissent, la fiche est produite avec couverture `partial` et limitation visible.

### FR-006 — Conserver une preuve minimale avant synthèse

- **Priorité :** Must
- **Exigence :** avant qu’un fait soit généré, le produit doit conserver une preuve identifiée contenant la provenance minimale définie dans ce PRD.
- **Rationale/source :** invariant 1; audit et hallucination.

#### Acceptance criteria

- **AC-FR-006-01 Primary:** chaque `evidence_id` résout vers une URL, une date de collecte, un type, une relation de source, un état d’accès et un extrait pertinent.
- **AC-FR-006-02 Duplicate:** la reprise d’une même URL et même version ne crée pas deux preuves distinctes pour gonfler le recoupement.
- **AC-FR-006-03 Unavailable later:** si l’URL devient indisponible après collecte, la fiche conserve la provenance et signale l’indisponibilité au lieu de supprimer silencieusement la preuve.
- **AC-FR-006-04 Data minimization:** l’extrait conservé est limité au passage nécessaire; les données personnelles incidentes non requises sont exclues ou masquées dans la fiche.

### FR-007 — Classer l’identité de manière conservatrice

- **Priorité :** Must
- **Exigence :** après collecte, le produit doit attribuer exactement un statut d’identité selon la table normative et afficher les attributs et preuves ayant conduit à la décision.
- **Rationale/source :** risque principal du produit.

#### Acceptance criteria

- **AC-FR-007-01 Confirmed:** trois attributs concordants sur deux sources indépendantes, dont une adresse ou un contact corporate, et sans contradiction forte produisent `confirmed`.
- **AC-FR-007-02 Probable:** deux attributs concordants sur deux sources, dont un attribut à forte spécificité, sans troisième confirmation produisent au plus `probable`.
- **AC-FR-007-03 Ambiguous:** deux entités plausibles ou une contradiction forte non résolue produisent `ambiguous`.
- **AC-FR-007-04 Not found:** aucun candidat après le protocole minimal produit `not_found` avec les catégories de sources tentées.
- **AC-FR-007-05 Conservative override:** le système choisit le statut le plus faible lorsque les règles entrent en conflit.

### FR-008 — Sourcer et classer chaque fait important

- **Priorité :** Must
- **Exigence :** lorsqu’un fait important est affiché, le produit doit lui associer au moins une preuve et un statut calculé selon les règles de faits.
- **Rationale/source :** promesse centrale de fiabilité.

#### Acceptance criteria

- **AC-FR-008-01 Primary:** chaque fait affiche valeur, statut, date pertinente si connue et liens vers ses preuves.
- **AC-FR-008-02 Unsupported:** une affirmation sans preuve n’apparaît pas comme fait; elle devient `non trouvé` ou note d’hypothèse explicite.
- **AC-FR-008-03 Probable identity:** un fait issu d’une entité seulement `probable` ne peut pas être `confirmed`.
- **AC-FR-008-04 Stale:** un fait potentiellement ancien affiche la date de publication ou, à défaut, la date de collecte et une limitation de fraîcheur.

### FR-009 — Exposer les contradictions

- **Priorité :** Must
- **Exigence :** lorsque des preuves pertinentes divergent, le produit doit créer une contradiction structurée sans choisir silencieusement une valeur.
- **Rationale/source :** brief de découverte et risque d’adresse contradictoire.

#### Acceptance criteria

- **AC-FR-009-01 Primary:** chaque contradiction présente le champ, les valeurs concurrentes, leurs preuves et son état de résolution.
- **AC-FR-009-02 Strong conflict:** une contradiction forte abaisse l’identité à `ambiguous` jusqu’à résolution conforme.
- **AC-FR-009-03 Temporal:** si des dates permettent d’expliquer une évolution, le produit peut présenter l’ancienne et la nouvelle valeur, mais conserve les deux preuves.
- **AC-FR-009-04 Review:** le relecteur peut commenter ou demander une révision, pas effacer une valeur contradictoire de l’historique.

### FR-010 — Rendre les absences et limites explicites

- **Priorité :** Must
- **Exigence :** à la fin d’une exécution, le produit doit distinguer un champ non trouvé, une catégorie non recherchée et une source inaccessible.
- **Rationale/source :** éviter une impression trompeuse de complétude.

#### Acceptance criteria

- **AC-FR-010-01 Not found:** chaque élément `not_found` indique le champ et le périmètre de recherche tenté.
- **AC-FR-010-02 Not searched:** une catégorie non tentée est étiquetée `non recherchée`, avec la raison.
- **AC-FR-010-03 Unavailable:** une dépendance ou source inaccessible est étiquetée `indisponible`, avec couverture `partial` si elle réduit le protocole.
- **AC-FR-010-04 Empty result:** une fiche sans fait utile reste consultable avec identité, journal, limites et décision de revue.

### FR-011 — Générer une fiche courte et vérifiable

- **Priorité :** Must
- **Exigence :** lorsque la collecte se termine, le produit doit produire une vue KAM et une représentation structurée conformes au même schéma versionné.
- **Rationale/source :** résultat utilisateur et contrat de sortie.

#### Acceptance criteria

- **AC-FR-011-01 Primary:** la vue présente dans cet ordre identité, résumé, faits par rubrique, contradictions, non trouvés, limites et revue.
- **AC-FR-011-02 Traceability:** un clic ou une action équivalente depuis chaque fait ouvre sa preuve ou sa provenance conservée.
- **AC-FR-011-03 Consistency:** la vue et le JSON ne divergent pas sur les valeurs, statuts ou preuves.
- **AC-FR-011-04 Status:** une fiche `awaiting_review` porte visiblement la mention `Non revue`.

### FR-012 — Capturer la validation humaine et l’utilité

- **Priorité :** Must
- **Exigence :** lorsqu’une fiche est disponible, un relecteur doit pouvoir accepter, rejeter ou demander une révision, qualifier son utilité et documenter les erreurs observées.
- **Rationale/source :** objectif d’apprentissage et garde-fou avant industrialisation.

#### Acceptance criteria

- **AC-FR-012-01 Accept:** une acceptation enregistre relecteur, date, utilité `utile | partiellement utile | non utile` et commentaire optionnel.
- **AC-FR-012-02 Reject:** un rejet exige au moins un motif parmi `mauvaise identité`, `fait non sourcé`, `contradiction manquée`, `fiche trop pauvre`, `autre`.
- **AC-FR-012-03 Revision:** une demande de révision conserve la fiche originale et lie la version corrigée.
- **AC-FR-012-04 Permission:** seuls les KAM relecteurs ou opérateurs autorisés peuvent enregistrer une décision.

### FR-013 — Préserver l’audit et le versionnage

- **Priorité :** Must
- **Exigence :** le produit doit conserver un historique append-only des transitions, corrections, réexécutions et décisions de revue pendant la période de conservation applicable.
- **Rationale/source :** rejouabilité, audit et diagnostic.

#### Acceptance criteria

- **AC-FR-013-01 Primary:** chaque transition contient acteur ou système, date, ancien état, nouvel état et identifiant de version.
- **AC-FR-013-02 Correction:** corriger un fait crée une nouvelle version et garde le lien vers la preuve ajoutée ou retirée.
- **AC-FR-013-03 Replay:** à partir du seed, du journal, des preuves et de la version des règles, un opérateur peut expliquer comment la fiche a été produite.
- **AC-FR-013-04 Deletion:** une suppression autorisée laisse uniquement la trace minimale d’audit permise par la politique adoptée; la politique reste à décider avant pilote élargi.

### FR-014 — Exclure les données personnelles non nécessaires

- **Priorité :** Must
- **Exigence :** pendant la collecte et la restitution, le produit doit exclure les recherches ciblant une personne et ne présenter comme contact que des coordonnées explicitement corporate.
- **Rationale/source :** exclusion du brief et protection de la personne concernée.

#### Acceptance criteria

- **AC-FR-014-01 Corporate contact:** un standard, une adresse générique ou un contact publié explicitement comme contact d’entreprise peut être affiché avec sa source.
- **AC-FR-014-02 Ambiguous contact:** un téléphone ou email dont le caractère corporate n’est pas établi est masqué de la fiche et signalé `à confirmer` sans valeur personnelle.
- **AC-FR-014-03 Personal profile:** un profil individuel ou une information sur un salarié n’est pas ajouté à la fiche, même s’il est public.
- **AC-FR-014-04 Search log:** le journal ne contient pas de requête ciblant une personne.

### FR-015 — Gérer interruption, annulation et reprise

- **Priorité :** Must
- **Exigence :** lorsqu’une collecte échoue ou est interrompue, le produit doit préserver l’état connu, éviter les doublons et indiquer au KAM l’issue certaine de l’exécution.
- **Rationale/source :** fiabilité et récupération.

#### Acceptance criteria

- **AC-FR-015-01 Failure:** l’exécution passe à `failed` avec étape et message compréhensible, sans exposer de secret technique.
- **AC-FR-015-02 Partial completion:** si une fiche exploitable existe malgré une dépendance échouée, elle passe à `awaiting_review` avec couverture `partial` plutôt qu’à un faux succès complet.
- **AC-FR-015-03 Cancel:** après annulation, aucune nouvelle collecte n’est initiée pour cette exécution.
- **AC-FR-015-04 Resume:** une relance réutilise les preuves déjà valides sans les compter comme sources indépendantes supplémentaires.

<!-- prd-section: data-privacy-quality -->
## Data, Privacy, and Quality Requirements

### Catégories de données et cycle de vie

| Catégorie | Source et finalité | Visibilité | Sensibilité et usage interdit | Cycle de vie requis |
|---|---|---|---|---|
| Seed ARSP | Import ARSP; identifier et rechercher l’entreprise | KAM et opérateur autorisés | Peut contenir des coordonnées ambiguës; aucune prospection dans ce produit | Instantané versionné; correction par nouvelle version |
| Preuves publiques | Pages et documents publics; justifier les faits | KAM/relecteur et opérateur | Extraits minimaux; ne pas constituer de dossier personnel | Conserver pour revue et audit selon une durée à décider; suppression possible |
| Faits et identité dérivés | Générés depuis les preuves; produire la fiche | KAM/relecteur et opérateur | Ne jamais présenter une inférence comme fait | Versionnés avec règles et preuves |
| Journal de recherche | Requêtes, URLs, étapes, erreurs | Opérateur; synthèse de couverture pour KAM | Aucune requête ciblant une personne; aucun secret dans les messages | Append-only pendant la période applicable |
| Revue humaine | Décision, utilité, motifs, commentaires | KAM/relecteur et opérateur | Éviter les données personnelles libres non nécessaires | Versionnée; corrigeable sans effacer l’historique autorisé |
| Télémétrie produit | Durées, statuts, compteurs qualité | Product/Opérations, agrégée lorsque possible | Pas de contenu de preuve dans les événements analytiques | Minimisation et durée à décider avant pilote élargi |

### NFR-001 — Intégrité de provenance

Pour toute fiche soumise à revue, 100 % des faits importants doivent référencer au moins une preuve valide dans l’exécution. Vérification : contrôle automatique du schéma puis revue manuelle ligne par ligne.

### NFR-002 — Transparence de l’IA

Le produit doit afficher le statut d’identité, le statut de chaque fait, les limites de couverture et le statut de revue sans que le KAM ait à ouvrir le journal technique. Une formulation générée ne doit pas supprimer ces indicateurs.

### NFR-003 — Réactivité et progression

- Cible provisoire : accusé de lancement visible en moins de 2 secondes et premier état de progression en moins de 5 secondes.
- Cible provisoire : 90 % des recherches du test terminent ou retournent une fiche partielle explicite en moins de 10 minutes.
- Au-delà de 10 minutes, le KAM voit l’étape active et peut annuler; ces seuils seront révisés après les trois cas.

### NFR-004 — Reproductibilité

Une fiche doit identifier la version du schéma, la version des règles, le seed, les preuves et le journal utilisés. Une réexécution ultérieure peut produire un résultat différent, mais ne doit pas modifier rétroactivement la version antérieure.

### NFR-005 — Accessibilité et langue

La fiche et les commandes de revue doivent être utilisables au clavier, conserver un ordre de lecture logique et exposer des libellés textuels pour les statuts. Le prototype est en français; les textes de source restent dans leur langue d’origine et peuvent être résumés en français sans altérer la preuve.

### NFR-006 — Confidentialité et contrôle d’accès

Seuls les utilisateurs internes autorisés peuvent lancer ou consulter une recherche. Les refus d’accès ne doivent révéler ni le contenu d’une fiche ni l’existence d’une recherche à un utilisateur non autorisé. Toute consultation ou modification de revue est auditée pendant la période applicable.

### NFR-007 — Dégradation explicite

Une dépendance lente ou indisponible ne doit pas transformer une exécution partielle en fiche complète. Le produit conserve les éléments valides, nomme les catégories non couvertes et permet une reprise sans duplication.

### Décision de conservation

La durée de conservation et la procédure d’exercice des droits ne sont pas fixées par les sources disponibles. Pour le prototype limité, Onbora doit conserver uniquement ce qui est nécessaire à la revue des trois cas, limiter l’accès et supprimer les copies de travail devenues inutiles à la clôture. Avant pilote élargi, Product/Data/Legal doit approuver une durée, les déclencheurs de suppression, les exceptions d’audit et la procédure de correction ou suppression.

<!-- prd-section: metrics-and-analytics -->
## Metrics and Analytics

| ID | Question produit | Définition et fenêtre | Cible ou statut | Garde-fou | Décision et owner |
|---|---|---|---|---|---|
| MET-001 | L’agent associe-t-il la bonne entité ? | Exécutions dont le statut d’identité est jugé correct par la revue / exécutions revues, segmentées par profil de visibilité; sur les 3 cas | Cible proposée : 100 %; non mesuré | Toute association fausse présentée `confirmed` déclenche un no-go | Product + KAM relecteur |
| MET-002 | La fiche est-elle utile ? | Fiches notées `utile` ou `partiellement utile` / fiches revues; sur les 3 cas, sans déduplication d’une même version | Seuil proposé : au moins 2 sur 3; non mesuré | Rapporter séparément `utile` et `partiellement utile`; ne pas compenser une erreur d’identité | Product |
| MET-003 | Les faits importants sont-ils tous sourcés ? | Faits importants avec au moins une preuve valide / faits importants affichés, par fiche et globalement | 100 % obligatoire | Nombre de faits importants non sourcés = 0 | Opérations + QA |
| MET-004 | Les contradictions sont-elles visibles ? | Contradictions pertinentes affichées / contradictions identifiées par la revue manuelle de l’échantillon | 100 % sur le test; non mesuré | Une contradiction forte manquée déclenche correction avant poursuite | KAM relecteur |
| MET-005 | La recherche est-elle plus exploitable que l’alternative manuelle ? | Temps médian de lancement à `awaiting_review`, temps de revue et appréciation KAM comparés à une recherche manuelle de référence | Baseline à établir; aucune cible ferme | La vitesse ne compense ni erreur d’identité ni fait non sourcé | Product |
| MET-006 | Quelle est la couverture par profil ? | Nombre de faits `confirmed`, `probable`, `conflicting` et `non trouvé` par profil de visibilité et catégorie de source | Descriptif; non mesuré | Ne pas optimiser le volume de faits au détriment de la fiabilité | Product |
| MET-007 | Quel est le coût opérationnel ? | Durée machine, volume de pages tentées, pages retenues et minutes humaines par exécution | Baseline à établir | Aucun élargissement sans coût unitaire lisible | Opérations |

Événements minimaux : `research_requested`, `research_started`, `source_attempted`, `evidence_saved`, `identity_classified`, `brief_ready`, `review_submitted`, `research_failed`, `research_cancelled`. Chaque événement porte `request_id`, `run_id`, horodatage, version du schéma et profil de test; aucun extrait de preuve ni donnée personnelle n’est requis dans la télémétrie.

<!-- prd-section: dependencies-rollout-risks -->
## Dependencies, Rollout, and Risks

### Dépendances et intégrations

- Base ARSP locale ou importée avec `Numéro Dossier` et dénomination.
- Accès à des moteurs et pages publiques. L’indisponibilité doit produire une dégradation explicite.
- Stockage contrôlé des preuves, journaux, versions et revues.
- Un KAM ou opérateur disponible pour la validation manuelle.
- SearXNG local et Trafilatura sont des options de prototype, pas des dépendances contractuelles.
- Aucun CRM, réseau social authentifié, système d’envoi ou API payante n’est requis.

### Rollout d’apprentissage

1. **Cas A — forte empreinte :** nom distinctif, plusieurs sources et présence officielle attendue.
2. **Cas B — empreinte partielle :** absence possible de site, mais sources sociales, presse, partenaires, appels d’offres ou annuaires.
3. **Cas C — quasi invisible ou ambigu :** peu de traces, homonymie ou contradictions attendues.
4. Le même protocole et la même version de règles s’appliquent aux trois cas.
5. Chaque fiche est revue ligne par ligne et les métriques sont enregistrées avant le cas suivant; une erreur grave est corrigée avant de poursuivre.

### Go, no-go et fallback

- **Go vers un pilote limité :** MET-001 = 100 %, MET-003 = 100 %, MET-004 = 100 %, au moins deux fiches sur trois jugées utiles ou partiellement utiles, aucune donnée personnelle non nécessaire affichée, coût unitaire documenté et politique de conservation approuvée.
- **Itération du protocole :** identité correctement prudente mais couverture ou utilité insuffisante; réviser requêtes, catégories de sources ou format, puis retester sans élargir.
- **No-go/pivot :** une mauvaise entité est présentée comme `confirmed`, un fait important non sourcé subsiste après revue, les contradictions fortes sont masquées, ou moins de deux fiches sont utiles après une itération.
- **Fallback :** recherche manuelle KAM en utilisant la fiche comme grille de collecte; aucune donnée issue d’une exécution rejetée n’est réutilisée comme vérité.

| ID | Risque, hypothèse ou décision ouverte | Impact | Mitigation ou défaut | Validation | Owner / blocage |
|---|---|---|---|---|---|
| RISK-001 | Mauvaise entité associée | Fiche convaincante mais erronée; perte de confiance | Statut conservateur, attribut fort, deux sources, revue obligatoire | MET-001 et cas C | Product + KAM; bloque l’élargissement |
| RISK-002 | Sources dupliquées ou se recopiant | Faux recoupement | Dédupliquer domaine/contenu et documenter l’indépendance | Revue des preuves du cas A/B | Opérations |
| RISK-003 | Information ancienne | Mauvaise préparation du KAM | Dates, statut probable, contradiction temporelle et limitation | Revue du cas avec adresse divergente | KAM |
| RISK-004 | Faits non sourcés ou hallucination | Décision fondée sur une invention | Validation automatique 100 % + revue ligne par ligne | MET-003 | QA; no-go si non nul |
| RISK-005 | Présence publique trop faible | Fiche pauvre | `not_found`, couverture explicite, cas C, fallback manuel | MET-006 et appréciation KAM | Product |
| RISK-006 | Donnée personnelle prise pour contact corporate | Atteinte à la personne et usage indu | Exclusion, masquage, règle corporate explicite | Revue FR-014 sur chaque fiche | Product/Data; bloque l’élargissement si non résolu |
| RISK-007 | Dépendance web indisponible ou restrictive | Recherche incomplète | Couverture `partial`, pas de contournement, reprise | Test d’échec contrôlé | Opérations |
| RISK-008 | Politique de conservation absente | Exposition et non-conformité lors du scale | Minimisation pendant le test; décision formelle avant pilote | Décision Product/Data/Legal | Bloque le pilote élargi, pas les 3 cas contrôlés |
| RISK-009 | Seuil d’utilité KAM mal défini | Faux signal de succès | Échelle structurée et commentaire; entretien après chaque cas | MET-002 | Product |
| RISK-010 | SearXNG/Trafilatura sous-couvrent certaines sources | Résultats biaisés | Les traiter comme hypothèses techniques; mesurer catégories manquées | MET-006/MET-007 | Architecture après PRD |

### Decision ledger

| ID | Décision | Statut | Compromis | Déclencheur de révision | Owner |
|---|---|---|---|---|---|
| DEC-001 | `Numéro Dossier` est l’identifiant stable de la ligne source. | Acceptée pour le prototype | Dépend de la qualité de chaque nouvelle importation | Doublon ou valeur manquante dans une nouvelle version ARSP | Product/Data |
| DEC-003 | La revue humaine est obligatoire avant acceptation. | Acceptée | Coût manuel assumé | Qualité prouvée sur un échantillon plus large et décision explicite | Product |
| DEC-004 | Les statuts d’identité et de faits suivent les tables normatives de ce PRD. | Acceptée pour test | Peut réduire la couverture apparente | Trop de faux négatifs démontrés sans hausse du risque | Product + KAM |
| DEC-005 | Pas de session sociale ni service payant dans le prototype. | Acceptée | Certaines sources resteront inaccessibles | Couverture insuffisante démontrée sur les trois cas | Product + Architecture |
| DEC-006 | Conservation au-delà du test contrôlé. | Ouverte | Auditabilité contre minimisation | Avant le premier pilote élargi | Product/Data/Legal |

<!-- prd-section: traceability-and-readiness -->
## Traceability and Readiness

| Outcome ou parcours | Exigences | Acceptation | Métriques | Risques |
|---|---|---|---|---|
| Identifier sans confusion la ligne et l’entité | FR-001, FR-002, FR-007 | AC-FR-001-*, AC-FR-002-*, AC-FR-007-* | MET-001 | RISK-001, RISK-003 |
| Produire une recherche publique auditée | FR-003 à FR-006, FR-013, FR-015 | AC-FR-003-* à AC-FR-006-*, AC-FR-013-*, AC-FR-015-* | MET-005, MET-006, MET-007 | RISK-002, RISK-007, RISK-010 |
| Restituer uniquement des faits vérifiables | FR-008 à FR-011, FR-014 | AC-FR-008-* à AC-FR-011-*, AC-FR-014-* | MET-003, MET-004, MET-006 | RISK-003, RISK-004, RISK-006 |
| Valider la valeur pour le KAM | FR-012 | AC-FR-012-* | MET-002, MET-005 | RISK-005, RISK-009 |

### PRD stress test

- **Deux équipes pourraient-elles produire des comportements différents ?** Le risque principal concernait les seuils `confirmed`, `probable`, `ambiguous` et `not_found`; les tables normatives et cas d’acceptation les fixent désormais.
- **Un Must peut-il être retiré ?** Non sans casser le parcours critique, la traçabilité, la protection des personnes ou l’apprentissage humain. L’export et l’URL manuelle restent hors du noyau.
- **Hypothèse la plus menaçante :** ASM-001, la capacité à résoudre l’identité à partir de traces publiques inégales.
- **Élément facile à oublier :** distinguer `non trouvé`, `non recherché`, `source indisponible` et `couverture partielle`.
- **Métrique trompeuse :** augmenter le nombre de faits peut dégrader la fiabilité; MET-003, MET-004 et le no-go sur mauvaise identité protègent contre ce biais.

### Definition of Ready

| Critère | Statut |
|---|---|
| Acteurs, résultat, périmètre et non-objectifs explicites | Satisfait |
| Contrat d’entrée et de sortie versionné | Satisfait |
| Règles d’identité, de faits, de contradiction et d’absence définies | Satisfait |
| Parcours principal, erreurs, reprise et versionnage définis | Satisfait |
| Musts reliés à une preuve, un objectif ou un garde-fou | Satisfait |
| Critères d’acceptation et métriques d’apprentissage définis | Satisfait |
| Données personnelles exclues du résultat produit | Satisfait |
| Politique de conservation approuvée pour un pilote au-delà des trois cas | Ouvert; bloque uniquement l’élargissement |
| Trois entreprises pilotes nommées et un KAM relecteur désigné | Ouvert; requis avant exécution du test |

- **Readiness :** `ready with assumptions` pour les trois recherches contrôlées.
- **Blocage :** aucun pour l’expérimentation interne limitée. DEC-006 bloque tout pilote élargi ou traitement à plus grande échelle.

<!-- prd-section: handoff-for-architecture -->
## Handoff for Architecture

- **Objectif, acteurs et frontière :** permettre à un KAM interne de lancer une recherche publique unitaire sur une ligne ARSP et de revoir une fiche sourcée. Le système s’arrête avant scoring, recommandation, CRM ou contact.
- **Parcours critique :** sélection par `Numéro Dossier` → instantané du seed → exécution idempotente → journal de recherche → preuve conservée → résolution d’identité → faits et contradictions → fiche `Non revue` → décision humaine versionnée.
- **États à préserver :** exécution, couverture, identité, fait et revue sont des dimensions distinctes. Aucun état partiel ne doit être présenté comme complet ou validé.
- **Permissions :** KAM autorisé pour lancement et revue; opérateur pour reprise, annulation et support; aucune visibilité externe. Une correction crée une version et ne réécrit pas l’historique.
- **Règles invariantes :** 100 % des faits importants ont une preuve; statut conservateur en cas de conflit; deux sources ne comptent comme indépendantes que si leur origine l’est; aucune prospection ni collecte ciblée de personne.
- **Données :** seed ARSP brut et normalisé, preuves publiques minimales, faits dérivés, journal, versions et revue. Les preuves et la synthèse restent séparées. Les données personnelles incidentes sont exclues de la fiche.
- **Cycle de vie :** instantanés et versions immuables pendant la durée autorisée; suppression et exceptions d’audit à définir avant élargissement.
- **Contrats externes :** accès public uniquement, sans authentification ni contournement. L’indisponibilité produit une couverture `partial` et un journal exploitable.
- **Qualité mesurable :** provenance à 100 %, transparence des statuts, accusé de lancement < 2 s, progression < 5 s, cible provisoire de résultat ou fiche partielle < 10 min dans 90 % des cas, accessibilité clavier et libellés textuels.
- **Rollout et fallback :** trois cas ordonnés par visibilité; revue après chaque cas; arrêt immédiat sur mauvaise identité confirmée ou fait important non sourcé; fallback vers recherche manuelle structurée.
- **Risques et hypothèses :** RISK-001, RISK-004, RISK-006 et ASM-001 dominent. SearXNG et Trafilatura restent des hypothèses que l’architecture peut remplacer sans changer le comportement produit.
- **Décisions ouvertes :** durée de conservation, entreprises pilotes, relecteur nommé, seuil de temps confirmé et éventuels formats d’export.
- **Readiness architecture :** prête pour une architecture de prototype sous ces hypothèses. L’architecture ne doit pas redéfinir les statuts, seuils de preuve, exclusions de données ou règles de revue.
