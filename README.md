# Onbora Company Research Agent

Application Django interne de recherche d’entreprises ARSP. Le prototype
`essai/` reste intact ; son moteur SearXNG/Trafilatura a été intégré au worker
Django avec une persistance des recherches et des preuves.

## Ce qui est implémenté

- import XLSX ARSP immuable avec valeurs brutes et variantes normalisées ;
- rôles Django (`kam`, `reviewer`, `operator`, `admin`) et audit d’actions ;
- création idempotente, consultation restreinte et annulation des recherches ;
- interface web pour chercher une ligne ARSP et consulter une exécution ;
- recherche initiale complète avec OpenAI, limitée à un appel web par entreprise ;
- moteur SearXNG de secours avec requêtes d'identité puis enrichissement ;
- déduplication et préclassement des liens avant téléchargement ;
- inventaire complet et cliquable de toutes les URLs trouvées, même non analysées ;
- récupération publique bornée (SSRF, redirections, MIME, taille et délai),
  avec une limite séparée pour les grandes pages ARSP ;
- extraction ciblée des lignes ARSP et extraction Trafilatura des autres pages ;
- stockage séparé des tentatives, captures et évaluations propres à chaque run.
- complément Gemini facultatif sur le parcours SearXNG sans OpenAI ;
- résumé IA séparé, dont chaque affirmation renvoie aux preuves capturées.
- segmentation sectorielle déterministe avec niveau de confiance et preuves publiques ;
- benchmark humain persistant sur des lots de 10 entreprises, avec comparaison
  entre les informations visibles dans les sources et le résultat Onbora.

La revue humaine complète prévue par le PRD n’est pas encore activée. L’IA
reste facultative : sans OpenAI, le parcours SearXNG reste disponible. Si OpenAI
échoue ou ne renvoie aucune URL exploitable, Onbora essaie SearXNG sans répéter
l'appel web payant. Ce secours nécessite un moteur SearXNG démarré.

## Configuration IA à faible coût

Le fichier `.env` peut contenir la clé déjà nommée `OPENAI` (ou
`OPENAI_API_KEY`). Quand elle est présente, OpenAI pilote la recherche initiale :

```dotenv
OPENAI=ta_cle_api
```

Le modèle par défaut est `gpt-6-luna`. Pour protéger un petit budget de test,
chaque recherche d'entreprise autorise au maximum **un appel de recherche web**,
retient cinq URLs et ne fait aucun retry automatique. Le résumé réutilise
uniquement les pages vérifiées, sans nouvel appel web. Il y a donc **un appel
API de recherche puis, si des preuves existent, un appel API de synthèse** ;
seul le premier a accès à la recherche web. Réglages optionnels :

```dotenv
ONBORA_OPENAI_ENABLED=1
ONBORA_OPENAI_MODEL=gpt-6-luna
ONBORA_OPENAI_MAX_SEARCH_SOURCES=5
ONBORA_OPENAI_TIMEOUT_SECONDS=45
```

Sans clé OpenAI, l'ancien complément Gemini reste disponible avec :

```dotenv
GEMINI_API_KEY=ta_cle_api
ONBORA_GEMINI_ENABLED=1
ONBORA_GEMINI_MODEL=gemini-3.5-flash-lite
ONBORA_GEMINI_MAX_SEARCH_SOURCES=8
ONBORA_GEMINI_TIMEOUT_MS=45000
```

La demande OpenAI regroupe identité, RCCM, activité, produits et services,
adresse, implantations, contacts professionnels, mentions indépendantes et
signaux commerciaux utiles à Orange RDC. Les URLs retournées passent par la
récupération et l'analyse Onbora ; une page inaccessible ou hors sujet ne peut
pas alimenter le résumé. Sur ce parcours, aucune requête SearXNG supplémentaire
n'est lancée pour le profil ou les leads : la qualification exploite les preuves
de cette recherche unique. Les informations absentes restent signalées.
Les compteurs `ai_search_request_count` et `ai_summary_request_count` sont
conservés dans le résultat pour distinguer les deux appels au modèle.

Sur le parcours SearXNG sans OpenAI, Gemini reste un complément après analyse
si aucune page n'a le verdict « Pertinente ».
Les pages ARSP peuvent atteindre `ONBORA_MAX_ARSP_PAGE_BYTES` (8 Mo par défaut) ;
les autres gardent `ONBORA_MAX_PAGE_BYTES` (2 Mo). Sur le parcours SearXNG, les requêtes commerciales
ne démarrent qu'après une preuve d'identité pertinente ; leur analyse est bornée
par `ONBORA_LEAD_ANALYSIS_LIMIT` (4 pages par défaut).
Si la première sélection ne donne aucune page pertinente, Onbora peut lire
quatre autres résultats SearXNG avant de demander le complément Gemini ; ce plafond
est réglable avec `ONBORA_RESCUE_ANALYSIS_LIMIT`.
Le moteur reconnaît aussi la marque sans suffixe juridique. Lorsqu’un email
ARSP utilise un domaine concordant avec cette marque, il explore directement
ce site et lit son titre HTML réel pour les sites dont le logo n’est pas extrait.
La concordance du domaine et du nom permet de retenir le site comme source de
l’entreprise ; elle ne prouve pas que le RCCM est publié sur ce site. Les sources
pertinentes et les sites ainsi rattachés passent avant les mentions incertaines
dans le paquet envoyé au modèle de synthèse.
La recherche web OpenAI est facturée par appel en plus des jetons du modèle ;
son prix dépend du compte et des tarifs OpenAI en vigueur.

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

Sur le parcours SearXNG, quand une identité pertinente est trouvée, cinq requêtes supplémentaires
cherchent des signaux liés aux implantations, aux parcours clients, aux
opérations mobiles, à la collaboration et à l’infrastructure. Un catalogue absent n’empêche pas la recherche générale ni
le résumé IA : seule la section commerciale est marquée indisponible.

## Démarrage le plus simple (Windows)

Python doit être installé. Avec une clé OpenAI activée, Docker et SearXNG ne
sont pas nécessaires au parcours principal. Double-clique sur
`LANCER.bat`, ou exécute :

```powershell
cd "C:\dev\onbora analysis"
.\lancer.ps1
```

Le script installe les dépendances, applique les
migrations, importe le classeur s’il ne l’est pas déjà, puis lance le worker et
Django. Sans OpenAI, il démarre aussi SearXNG et nécessite Docker Desktop.
Pour disposer du secours SearXNG avec OpenAI, lance `./lancer.ps1 -StartSearxng`.
Au premier lancement, il demande de créer un superutilisateur. Ouvre
ensuite <http://127.0.0.1:8006/> et connecte-toi avec ce compte.

Arrête Django avec `Ctrl+C`. Le worker est alors arrêté automatiquement. Pour
arrêter aussi SearXNG :

```powershell
docker compose -f .\essai\docker-compose.yml down
```

## Recherche SerpApi

Un onglet **SerpApi** ouvre une recherche indépendante sur `/serpapi/` pour tester
Google Maps, Google Web et Google News. Les scénarios couvrent la découverte
d’entreprises, leur profil, leurs actualités et leurs technologies / fournisseurs.
On peut sélectionner une entreprise de l’import ARSP actif (filtre par nom, nom
commercial, RCCM ou dossier), ou saisir librement une entreprise. La sélection
préremplit le nom et la province sans consommer de crédit. La requête reste
modifiable. Le mode **Recherche complète**, sélectionné par défaut,
lance Web, Maps et News en parallèle : trois appels et jusqu’à trois crédits hors
cache. Il conserve les résultats disponibles si un moteur échoue. Les modes avec
un seul moteur effectuent toujours un appel. Aucun appel IA, pagination ou retry
automatique n’est ajouté. Les essais sont conservés par utilisateur
et exportables en CSV ou JSON. Le bouton **Vérifier mon quota** utilise l’API de
compte gratuite, uniquement à la demande.

Ajoute la clé dans le `.env` existant, puis redémarre Django :

```dotenv
SERPAPI=ta_cle_api
```

`SERPAPI_API_KEY` et `SERPAPI_KEY` sont aussi acceptés, dans cet ordre de priorité
avant `SERPAPI`. Aucune dépendance supplémentaire n’est nécessaire. Sur une
installation existante, exécute `python manage.py migrate` pour créer l’historique.
Le worker n’est pas nécessaire à cet onglet. Voir [le guide des essais](research/SERPAPI.md).

## Multi Search

Ouvre `/multi-search/` (lien **Multi Search** dans la navigation) avec un compte
`kam`, `operator` ou `admin`. Sélectionne entre 1 et 5 entreprises dans l’import
ARSP actif, puis lance le lot. La sélection reste disponible pendant les
recherches et les changements de page.

Les fiches se mettent à jour automatiquement : résumé avec citations, sources
retenues et offres Orange RDC à explorer. Les pistes commerciales restent des
hypothèses à confirmer. Sans résumé exploitable, les extraits disponibles sont
affichés et l’absence de preuve est signalée. Le bouton **Copier les résumés et
liens** produit un texte par entreprise. Les lots restent dans l’historique.

La **Fiche entreprise**, disponible aussi dans le détail d’une recherche, met
en avant la description, l’activité, l’adresse / siège, les produits et services,
les implantations, les contacts professionnels et les autres faits utiles
(projets, partenaires, clients ou chiffres explicitement publiés). Chaque fait
web cite une page collectée ; les valeurs du registre ARSP sont affichées
séparément comme déclarées et à confirmer. Les rubriques inconnues indiquent
« Information non trouvée ». La copie inclut aussi ces rubriques et leurs sources.

Sur le parcours SearXNG, après une preuve d’identité pertinente, deux requêtes recherchent les
activités et les coordonnées, même lorsque la qualification Orange est désactivée.
Cette collecte supplémentaire lit au maximum trois nouvelles pages
(`ONBORA_PROFILE_ANALYSIS_LIMIT`). Les sites rattachés au contact ARSP conservent
des extraits ciblés plus longs, dont les informations utiles en fin de page.
Les blocs d’adresse et de contact du pied de page sont aussi conservés sur ces
sites, même lorsque l’extraction du texte principal les omet.
Le résumé reste un seul appel IA, avec un plafond de sortie de 2 600 jetons.
Les anciennes recherches bénéficient de l’affichage des données ARSP ; relance
une recherche pour obtenir les nouvelles rubriques issues du web.

Le lanceur démarre le worker avec `--concurrency 5`. Un double envoi du même
formulaire réutilise le lot ; une recherche déjà active pour ce compte est
réutilisée. Chaque entreprise avance indépendamment des échecs des autres.

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
python manage.py run_research_worker --loop --concurrency 5

# Fenêtre 3 — interface
python manage.py runserver
```

Un superutilisateur a automatiquement tous les rôles. Pour un compte normal,
attribue le groupe `kam`, `reviewer` ou `operator` depuis `/admin/`.

## Vérification

```powershell
python manage.py test research.tests.test_pipeline_quality
python manage.py test research
python manage.py check
```

`test_pipeline_quality` rejoue hors ligne des pages de registre, des homonymes,
une recherche de rattrapage et un dossier sans preuve. Il ne consomme pas d'API IA
ni de moteur web. Les recherches réelles restent utiles pour diagnostiquer la
disponibilité des sites, mais ne remplacent pas ces tests reproductibles.

`ONBORA_SECRET_KEY` est obligatoire quand `ONBORA_DEBUG=0`. Les limites de
collecte peuvent être ajustées avec `ONBORA_ANALYSIS_LIMIT`,
`ONBORA_SEARCH_RESULTS_PER_QUERY` et `ONBORA_MAX_PAGE_BYTES`.
