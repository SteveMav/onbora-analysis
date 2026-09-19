# Onbora Company Research Agent

Application Django interne de recherche d’entreprises ARSP. Le prototype
`essai/` reste intact ; son moteur SearXNG/Trafilatura a été intégré au worker
Django avec une persistance des recherches et des preuves.

## Ce qui est implémenté

- import XLSX ARSP immuable avec valeurs brutes et variantes normalisées ;
- rôles Django (`kam`, `reviewer`, `operator`, `admin`) et audit d’actions ;
- création idempotente, consultation restreinte et annulation des recherches ;
- interface web pour chercher une ligne ARSP et consulter une exécution ;
- plan de requêtes ciblées par nom, RCCM, localisation et activité ;
- déduplication et préclassement des liens avant téléchargement ;
- inventaire complet et cliquable de toutes les URLs trouvées, même non analysées ;
- récupération publique bornée (SSRF, redirections, MIME, taille et délai) ;
- extraction Trafilatura, classement de pertinence et extraits vérifiables ;
- stockage séparé des tentatives, captures et évaluations propres à chaque run.
- recherche complémentaire Gemini quand SearXNG est bloqué ou trop pauvre ;
- résumé Gemini séparé, dont chaque affirmation renvoie aux preuves capturées.
- segmentation sectorielle déterministe avec niveau de confiance et preuves publiques ;
- benchmark humain persistant sur des lots de 10 entreprises, avec comparaison
  entre les informations visibles dans les sources et le résultat Onbora.

La revue humaine complète prévue par le PRD n’est pas encore activée. Gemini
reste facultatif : une panne ou un quota épuisé ne masque jamais les résultats
SearXNG déjà obtenus.

## Configuration Gemini

Crée un fichier `.env` à la racine sans le versionner :

```dotenv
GEMINI_API_KEY=ta_cle_api
```

Le modèle par défaut est `gemini-3.5-flash-lite`. Les réglages optionnels sont :

```dotenv
ONBORA_GEMINI_ENABLED=1
ONBORA_GEMINI_MODEL=gemini-3.5-flash-lite
ONBORA_GEMINI_FALLBACK_MIN_RESULTS=3
ONBORA_GEMINI_MAX_SEARCH_SOURCES=8
ONBORA_GEMINI_TIMEOUT_MS=45000
```

Le complément Gemini utilise Google Search grounding lorsqu’une requête ou un
moteur SearXNG échoue, ou lorsque moins de trois résultats sont jugés pertinents.
Les URLs trouvées repassent ensuite par la récupération et l’analyse Onbora. Une
page inaccessible reste une piste non vérifiée et ne peut pas alimenter le résumé.
Le quota Google Search grounding dépend du plan associé à la clé Gemini.

## Qualification de leads Orange

Chaque recherche terminée rattache aussi l’entreprise à une taxonomie sectorielle
contrôlée (transport, mines, finance, santé, technologies, etc.). Le résultat
affiche le secteur principal, les activités secondaires plausibles, la confiance,
la valeur ARSP d’origine et les sources concordantes. Sans signal suffisant,
Onbora affiche « secteur à confirmer » au lieu de forcer une catégorie.

Chaque recherche terminée évalue uniquement les parcours commerciaux disposant
d’au moins une offre validée pour Orange RDC : réseau multi-sites, paiement et
communication client, mobilité et M2M, collaboration et productivité, puis
datacenter et continuité. Les offres cyber et les portefeuilles internationaux
ne sont pas proposés tant que leur disponibilité commerciale locale n’est pas
validée. Les cartes
affichées au KAM distinguent un signal public prouvé, une simple compatibilité de
secteur ARSP et une information encore manquante. Elles ne prétendent jamais
connaître l’intention d’achat de l’entreprise.

Le catalogue Orange versionné est lu par défaut depuis
`..\onbora mvp\catalog\versions\v1\catalog.json`. Il peut être monté ailleurs :

```dotenv
ONBORA_OFFER_CATALOG_PATH=C:\chemin\vers\catalog.json
ONBORA_LEAD_QUALIFICATION_ENABLED=1
```

Quand la qualification est activée, cinq requêtes de recherche supplémentaires
cherchent des signaux liés aux implantations, aux parcours clients, aux
opérations mobiles, à la collaboration et à l’infrastructure. Un catalogue absent n’empêche pas la recherche générale ni
le résumé Gemini : seule la section commerciale est marquée indisponible.

## Démarrage le plus simple (Windows)

Docker Desktop et Python doivent être installés. Double-clique sur
`LANCER.bat`, ou exécute :

```powershell
cd "C:\dev\onbora analysis"
.\lancer.ps1
```

Le script installe les dépendances, démarre le SearXNG local, applique les
migrations, importe le classeur s’il ne l’est pas déjà, puis lance le worker et
Django. Au premier lancement, il demande de créer un superutilisateur. Ouvre
ensuite <http://127.0.0.1:8000/> et connecte-toi avec ce compte.

Arrête Django avec `Ctrl+C`. Le worker est alors arrêté automatiquement. Pour
arrêter aussi SearXNG :

```powershell
docker compose -f .\essai\docker-compose.yml down
```

## Benchmark humain

Les comptes `reviewer`, `operator` et `admin` disposent d’un lien **Benchmark
humain** dans la navigation. Un benchmark peut sélectionner 10 entreprises au
hasard dans l’import actif et lancer les recherches manquantes, ou réutiliser
les 10 recherches terminées les plus récentes. Pour chaque entreprise, le
reviewer ouvre les liens, consigne les faits trouvés manuellement, indique ce
qu’Onbora a manqué et qualifie l’identité ainsi que l’utilité du résultat. Les
métriques de couverture se mettent à jour à chaque enregistrement.

## Démarrage manuel

Utilise trois fenêtres PowerShell :

```powershell
# Fenêtre 1 — moteur de recherche
docker compose -f .\essai\docker-compose.yml up -d

# Première préparation seulement
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py import_arsp .\liste_entreprises_arsp.xlsx
python manage.py createsuperuser

# Fenêtre 2 — worker
python manage.py run_research_worker --loop

# Fenêtre 3 — interface
python manage.py runserver
```

Un superutilisateur a automatiquement tous les rôles. Pour un compte normal,
attribue le groupe `kam`, `reviewer` ou `operator` depuis `/admin/`.

## Vérification

```powershell
python manage.py test research
python manage.py check
```

`ONBORA_SECRET_KEY` est obligatoire quand `ONBORA_DEBUG=0`. Les limites de
collecte peuvent être ajustées avec `ONBORA_ANALYSIS_LIMIT`,
`ONBORA_SEARCH_RESULTS_PER_QUERY` et `ONBORA_MAX_PAGE_BYTES`.
