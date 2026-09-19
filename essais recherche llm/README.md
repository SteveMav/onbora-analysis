# Onbora — essais recherche LLM

Petit prototype Tkinter de recherche et qualification B2B. Il charge les entreprises
du fichier `../liste_entreprises_arsp.xlsx` et les 41 services du catalogue Orange
Business v1, puis utilise Gemini avec Google Search pour chercher des signaux publics
et apprécier la pertinence de plusieurs offres B2B.

Le rapport ne dit jamais qu'une entreprise est « intéressée » : il classe chaque offre
comme **Prioritaire**, **À explorer** ou **Non qualifiable** et donne les éléments à
vérifier. Les liens retournés par Google Search sont affichés dans l'onglet **Sources
à vérifier** ; ouvre-les avant toute prospection. Les appels utilisent l'Interactions
API avec `store=false` : le prototype ne conserve pas de conversation côté Gemini.

## Préparation

La clé reste hors du dossier et hors du code. Crée ou complète le fichier `.env` à la
racine de `C:\dev\onbora analysis` :

```dotenv
GEMINI_API_KEY=ta_cle_gemini
# Facultatif : modèle à employer par ce prototype
LLM_RESEARCH_MODEL=gemini-3.6-flash
```

Si le projet principal possède déjà `GEMINI_API_KEY`, aucune copie de clé n'est
nécessaire. Le modèle par défaut est `gemini-3.6-flash`, car `gemini-2.5-flash`
n'est plus disponible pour les nouvelles clés. Le lanceur met à niveau
`google-genai` vers une version compatible avec l'Interactions API.

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

## Dépannage Gemini

Si l'application indique que le quota est indisponible ou épuisé, la clé est bien
reconnue mais le projet Gemini n'a plus de quota utilisable pour cette requête.
Vérifie les limites, le plan et la facturation dans Google AI Studio, puis relance
la recherche. Une nouvelle clé ou un quota disponible est nécessaire : le code ne
peut pas contourner cette limite.

## Vérifier le code

```powershell
cd "C:\dev\onbora analysis\essais recherche llm"
python -m unittest -v test_app.py
```

Les tests n'appellent pas Gemini et ne consomment aucun quota.
