# Tester SerpApi pour Onbora

Documentation officielle consultée le 23 octobre 2026. Le point de départ métier
est le [chat de recherche partagé](https://chatgpt.com/share/6adb83bb-5030-83ea-98fa-4966caf77c5a) :
découvrir des sociétés en RDC et trouver des informations utiles à la préparation
des visites commerciales.

## Utilisation

1. Configure `SERPAPI=ta_cle_api` dans le `.env` à la racine. Les alias
   `SERPAPI_API_KEY` puis `SERPAPI_KEY` sont prioritaires si plusieurs clés existent.
2. Applique `python manage.py migrate`, puis démarre ou redémarre Django.
3. Connecte-toi avec un compte `kam`, `operator` ou `admin` et ouvre l’onglet
   **SerpApi**, à l’adresse `http://127.0.0.1:8006/serpapi/`.
4. Choisis **Saisie libre** ou **Choisir dans la base ARSP**. Dans le second cas,
   filtre par nom, nom commercial, RCCM ou dossier, puis clique sur **Choisir**
   à côté d’une entreprise. Le nom et la province préremplissent la requête ;
   tu peux encore la modifier. Le filtre et la sélection n’appellent pas SerpApi.
5. Le scénario **Recherche complète d’entreprise** sélectionne les trois moteurs
   par défaut. Tu peux aussi choisir un scénario avec un seul moteur. Saisis une
   entreprise ou une activité et une ville.
   **Préparer la requête** compose une proposition sans appeler l’API. Tu peux
   aussi écrire directement dans **Requête envoyée à SerpApi**.
6. Vérifie le moteur et la requête, puis lance un essai. L’historique permet
   de relire ou d’exporter les résultats sans nouvel appel API.

Le sélecteur de scénario propose le moteur adapté. Le bouton de préparation
réécrit la requête ; un simple changement de scénario conserve le texte saisi.
Sans JavaScript, la requête et le moteur restent saisissables directement.
La sélection ARSP porte sur une seule entreprise de l’import actif. L’essai
conserve son nom, son dossier et sa province dans l’historique et l’export JSON.
Ces informations identifient l’entrée de recherche ; elles ne prouvent pas que
chaque résultat web concerne cette entreprise. Aucun contact ARSP n’est envoyé
automatiquement au fournisseur. En saisie libre, une ancienne sélection cachée
est ignorée. Si l’import actif change, il faut sélectionner à nouveau l’entreprise
avant de relancer un essai lié à l’ancien import.

## Recherche complète : Web + Maps + News

Un seul lancement interroge les trois moteurs en parallèle, avec la même requête.
Pour un dossier d’entreprise, commence par son nom et sa ville, par exemple
`Rawbank Kinshasa RDC`. Les paramètres restent propres au moteur : pays pour Web
et News, coordonnées facultatives et `type=search` pour Maps.

Le bilan indique les résultats, la durée et les erreurs par moteur. Les résultats
sont présentés en trois sections et les exports identifient leur moteur d’origine.
Si un moteur échoue, les résultats des deux autres restent consultables et
exportables. Si les trois échouent, l’essai est marqué en échec, avec les trois
messages conservés. Aucun appel n’est relancé automatiquement.

Le lancement prévoit trois appels, donc jusqu’à trois crédits hors cache. Ce
compteur d’appels ne mesure pas les crédits effectivement consommés. Les résultats
cumulés peuvent contenir une même source dans plusieurs moteurs ; ils ne sont
pas présentés comme un nombre d’entreprises uniques. Le mode ne lit pas encore
les pages complètes et ne produit pas de synthèse IA.

## Quatre essais utiles

- **Découverte / Google Maps** : `entreprises logistiques Kinshasa RDC`.
  Obtenir des établissements, adresses, sites, téléphones publics et identifiants
  `place_id` lorsqu’ils existent. Le lien vers l’ARSP permet une première comparaison
  manuelle du nom. Il ne constitue pas un rapprochement d’identité automatique.
- **Profil / Google Web** : `"NOM ENTREPRISE" RDC activité services site officiel`.
  Retrouver des sources sur l’entreprise et explorer les activités et implantations.
- **Actualités / Google News** : `"NOM ENTREPRISE" RDC projet partenariat when:1y`.
  Repérer des articles récents. La date affichée est celle fournie par Google,
  sans interprétation automatique comme date d’immatriculation ou de projet.
- **Technologies / Google Web** : `"NOM ENTREPRISE" RDC réseau fournisseur transformation numérique`.
  Trouver des indices publics à recouper avant de proposer une offre Orange.

Le champ pays utilise `gl=cd` par défaut pour Web et News, et `hl=fr` règle
la langue. Maps reçoit `type=search` et, facultativement, `ll=@latitude,longitude,zoomz`.
La ville dans la requête reste utile : le centrage Maps ne garantit pas que tous
les résultats se trouvent dans la zone demandée.

## Ce que les résultats permettent d’évaluer

Répète les mêmes requêtes sur Kinshasa et Lubumbashi et sur quelques entreprises
connues. Exporte les résultats de chaque essai et vérifie dans les sources :

- l’existence et la localisation des entreprises trouvées ;
- les homonymes, doublons et établissements d’une même société ;
- la présence de sites, adresses et téléphones professionnels exploitables ;
- la fraîcheur des articles et leur intérêt pour une visite commerciale ;
- la durée de réponse et la consommation réelle du quota.

Les compteurs mesurent les résultats présentés, pas des entreprises uniques ni
une couverture exhaustive. Deux agences qui partagent un site restent distinctes.
La découverte d’une société absente de l’ARSP ne prouve pas sa création récente.
Les extraits seuls ne valident ni l’identité légale ni un besoin d’achat.

## Appels, coût et conservation

Le mode avec un seul moteur envoie un `GET https://serpapi.com/search.json` ; le
mode complet en envoie trois en parallèle. Chaque appel utilise un délai réseau
de 35 secondes, sans retry ni pagination. Chaque réponse est limitée à 4 Mo et
la présentation à 50 résultats par moteur hors publicités. News regroupe parfois plusieurs
articles : les rubriques `stories` et `highlight` sont aplaties et dédupliquées.
Web conserve aussi la fiche Google et les établissements locaux s’ils sont retournés.

`no_cache=false` autorise le cache du fournisseur. SerpApi indique qu’une réponse
en cache est gratuite si tous les paramètres sont identiques ; son cache expire
après une heure. Un appel n’est donc pas forcément un crédit consommé.
**Vérifier mon quota** appelle `account.json`, gratuitement selon la documentation.
Les offres et les tarifs sont à consulter directement dans le compte SerpApi.

Les essais conservent les paramètres, la date, la durée et les résultats normalisés.
La clé reste côté serveur ; les réponses brutes du fournisseur et les coordonnées
du titulaire du compte ne sont pas enregistrées. Chaque utilisateur ne consulte
et n’exporte que ses propres essais. La soumission possède un identifiant unique
pour éviter qu’un double envoi du même formulaire répète l’appel.

L’onglet fournit un banc d’essai du fournisseur. Il ne télécharge pas les pages
trouvées, ne génère pas de synthèse IA et n’importe pas automatiquement les
entreprises découvertes dans l’ARSP. L’ajout d’un enrichissement avec lecture des
pages et vérification d’identité pourra réutiliser les sources retenues après
ce test de couverture.

## Sources officielles

- [Google Search API](https://serpapi.com/search-api)
- [Google Maps API](https://serpapi.com/google-maps-api)
- [Google News API](https://serpapi.com/google-news-api)
- [Pays Google](https://serpapi.com/google-countries)
- [Account API](https://serpapi.com/account-api)
- [Statuts et erreurs](https://serpapi.com/api-status-and-error-codes)

## Vérification hors ligne

```powershell
python manage.py test research.tests.test_serpapi
```

Les tests simulent le fournisseur et ne consomment pas de quota.
