# Onbora — essais recherche LLM

Petit prototype Tkinter de recherche et qualification B2B. Il charge les entreprises
du fichier `../liste_entreprises_arsp.xlsx` et les 41 services du catalogue Orange
Business v1, puis utilise exclusivement `gpt-6-luna` avec la recherche web OpenAI pour chercher des signaux publics
et apprécier la pertinence de plusieurs offres B2B.

Le rapport ne dit jamais qu'une entreprise est « intéressée » : il classe chaque offre
comme **Prioritaire**, **À explorer** ou **Non qualifiable** et donne les éléments à
vérifier. Les liens cités par la recherche web sont affichés dans l'onglet **Sources
à vérifier** ; ouvre-les avant toute prospection. Les appels utilisent la Responses
API avec `store=false`.

## Préparation

La clé reste hors du dossier et hors du code. Crée ou complète le fichier `.env` à la
racine de `C:\dev\onbora analysis` :

```dotenv
OPENAI=ta_cle_openai
```

Si le projet principal possède déjà `OPENAI`, aucune copie de clé n'est
nécessaire. Ce prototype utilise toujours `gpt-6-luna`, sans sélection de modèle
par variable d'environnement. Le lanceur installe le SDK `openai` compatible.

Le catalogue est lu depuis :

```text
C:\dev\onbora mvp\catalog\versions\v1\catalog.json
```

S'il est déplacé, ajoute ce chemin alternatif au `.env` :

```dotenv
LLM_RESEARCH_CATALOG_PATH=C:\chemin\vers\catalog.json
```

## Lancer

Double-clique sur `LANCER.bat`, ou depuis PowerShell :

```powershell
cd "C:\dev\onbora analysis\essais recherche llm"
.\lancer.ps1
```

L'application crée un environnement Python isolé dans `.venv`, installe les
dépendances demandées si nécessaire, puis ouvre la fenêtre. Choisis une entreprise, filtre le catalogue,
sélectionne une ou plusieurs offres puis clique sur **Ajouter la sélection aux
offres**. Tu peux compléter manuellement les offres avant de lancer la recherche.

## Dépannage OpenAI

Si l'application signale une limite de débit ou de quota, vérifie les limites,
le plan et la facturation du projet OpenAI, puis relance la recherche.

## Vérifier le code

```powershell
cd "C:\dev\onbora analysis\essais recherche llm"
python -m unittest -v test_app.py
```

Les tests n'appellent pas OpenAI et ne consomment aucun quota.
