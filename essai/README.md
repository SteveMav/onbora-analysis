# Onbora — essai de recherche

Petit prototype volontairement simple :

1. charger les entreprises du fichier `../liste_entreprises_arsp.xlsx` ;
2. choisir une entreprise ;
3. compléter le secteur et des mots-clés comme `Kinshasa` ou `Lubumbashi` ;
4. interroger un SearXNG local ;
5. afficher les titres, sources, liens et résumés retournés ;
6. ouvrir et analyser localement les 5 premières pages, sans API payante.

## Lancer

Docker Desktop et Python doivent être installés.

Le plus simple est de double-cliquer sur `LANCER.bat`. Il démarre Docker si nécessaire, lance SearXNG puis ouvre l’application. La petite dépendance Python est installée automatiquement si elle manque.

Depuis PowerShell, la commande équivalente est :

```powershell
cd "C:\dev\onbora analysis\essai"
.\lancer.ps1
```

Au premier lancement, Docker télécharge l’image officielle SearXNG. Les lancements suivants la réutilisent.

Dans l’application, sélectionne une ligne de la liste. Le secteur et la province sont préremplis mais restent modifiables. Un double-clic sur un résultat ouvre sa page dans le navigateur.

Après la recherche, clique sur **Analyser les 5 premières pages**. L’application télécharge uniquement les pages web publiques, extrait leur texte principal avec Trafilatura et les classe ainsi :

- `Pertinente` : plusieurs éléments concordent avec la ligne ARSP ;
- `À vérifier` : le nom correspond, mais les autres éléments sont insuffisants ;
- `Hors sujet probable` : la page ne contient pas assez d’éléments concordants ;
- `Inaccessible` : page bloquée, supprimée, trop lourde ou non HTML.

Ce classement mesure la pertinence, pas la vérité. Les passages réellement extraits sont affichés pour permettre une vérification humaine.

Pour arrêter le moteur, double-clique sur `ARRETER.bat` ou utilise :

```powershell
.\arreter.ps1
```

## Vérifier le code

```powershell
python -m unittest -v test_app.py
```

SearXNG reste accessible uniquement sur la machine locale à l’adresse <http://127.0.0.1:8080>.
