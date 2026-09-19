# Onbora — recherche d’entreprise sourcée

## En une phrase

Onbora est un prototype interne qui aide un KAM à transformer une ligne de la base ARSP en une fiche d’entreprise courte, vérifiable et honnête sur ce qui reste incertain.

## Le problème

Avant un rendez-vous ou une prise de contact, un KAM dispose souvent d’un nom d’entreprise, d’un RCCM et de quelques coordonnées ARSP, mais manque de contexte fiable. La recherche web manuelle prend du temps, disperse les informations et peut facilement mélanger des entreprises aux noms proches.

L’enjeu n’est donc pas seulement de trouver davantage d’informations : il faut pouvoir dire **quelle information concerne réellement l’entreprise**, d’où elle vient et ce qui doit encore être confirmé.

## Ce que le projet fait

L’utilisateur recherche une entreprise dans la base ARSP puis lance une analyse. Le système :

```mermaid
flowchart LR
    A[Ligne ARSP] --> B[Requêtes ciblées]
    B --> C[Sources publiques]
    C --> D[Tri et conservation des preuves]
    D --> E[Analyse de pertinence et identité]
    E --> F[Fiche d'entreprise sourcée]
    F --> G[Validation humaine]
```

Les requêtes s’appuient notamment sur la dénomination, le RCCM, la localisation et l’activité déclarée. Les liens trouvés sont dédupliqués, puis les pages les plus prometteuses sont analysées. Chaque tentative — y compris une source inaccessible ou écartée — reste visible dans le journal de recherche.

## Ce que contient une fiche

Une fiche restitue de façon lisible :

- le statut d’identité : confirmée, probable, ambiguë ou non trouvée ;
- les informations utiles trouvées sur l’activité, l’implantation, la présence numérique ou l’actualité ;
- les sources et extraits qui permettent de vérifier ces informations ;
- les contradictions détectées, par exemple deux coordonnées ou adresses incompatibles ;
- les limites de la recherche et les informations qui n’ont pas pu être confirmées.

Une synthèse assistée par IA peut rendre la lecture plus rapide, mais elle est limitée aux preuves déjà collectées : toute affirmation doit renvoyer vers une source conservée par le système.

## Principes de fiabilité

Le projet privilégie la prudence plutôt qu’une fiche artificiellement complète.

- Une information importante sans source n’est pas présentée comme un fait.
- Une présence sur un réseau social ou un annuaire ne suffit pas seule à confirmer une identité.
- En cas de doute entre plusieurs entreprises, le résultat reste explicitement ambigu.
- Les sources, la date de collecte et les extraits sont conservés séparément du résumé.
- Le projet ne recherche pas de données personnelles sur les dirigeants ou salariés.

## Ce que le projet ne fait pas, volontairement

Cette première étape ne vise ni à noter le potentiel commercial d’une entreprise, ni à recommander une offre, ni à contacter automatiquement des prospects. Il ne s’agit pas non plus d’analyser toute la base ARSP en une seule fois.

L’objectif actuel est de valider la qualité de la recherche sur une entreprise à la fois, avant toute industrialisation.

## État actuel et prochaine validation

Le prototype permet déjà d’importer la base ARSP, de rechercher une entreprise, d’exécuter la collecte web, de conserver les preuves et d’afficher une fiche de recherche. Il peut s’appuyer sur SearXNG et Trafilatura pour la recherche et l’extraction de pages publiques, avec Gemini en complément facultatif lorsque la recherche est insuffisante.

La prochaine étape est une évaluation humaine sur des entreprises aux profils contrastés : une entreprise très visible en ligne, une entreprise avec une empreinte limitée et une entreprise presque absente du web. Cette évaluation doit vérifier trois choses :

1. les informations trouvées sont-elles réellement utiles à un KAM ?
2. l’entreprise associée aux sources est-elle la bonne ?
3. les contradictions et les absences sont-elles correctement expliquées ?

## La valeur recherchée

La valeur d’Onbora n’est pas de remplacer le jugement humain. Elle est de réduire le temps de préparation, de structurer les traces publiques disponibles et de rendre chaque conclusion vérifiable avant qu’un KAM l’utilise.
