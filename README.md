# 40k-events — tournois Warhammer 40 000 en France

Agrège les tournois 40k situés en France depuis deux sources et les affiche sur un
site statique (carte + liste + filtres). Aucune dépendance à installer : Python 3
(bibliothèque standard) pour la collecte, une page HTML pour l'affichage.

**Site : https://solberlight.github.io/40k-events/**

Les données sont rafraîchies chaque lundi à 04:00 UTC par le workflow GitHub
Actions `.github/workflows/update.yml`, qui relance les deux collecteurs, commite
les fichiers `data/*.json` et `site/events.js`, puis redéploie GitHub Pages. Le
workflow peut aussi être lancé à la main depuis l'onglet Actions (« Run workflow »).

## Sources et méthode

| Source | Accès | Script |
|---|---|---|
| Best Coast Pairings | API JSON non documentée mais publique, utilisée par leur front React : `GET https://newprod-api.bestcoastpairings.com/v1/events` avec l'en-tête `client-id: web-app`. Filtre géographique via le paramètre `location` (JSON, distance en miles), pagination par `nextKey`. | `scrape_bcp.py` |
| MiniHeadQuarters | Pas d'API. Pages Django rendues côté serveur : liste `/tournaments/individual/?country=FR&game_system=1&page_size=48&page=N`, puis chaque page de détail pour les coordonnées (marqueur Leaflet embarqué), l'adresse, le statut et le nombre de rondes. Les pages de détail sont mises en cache dans `cache/mhq/`. | `scrape_mhq.py` |

`build.py` fusionne les deux jeux de données, déduit département et région du code
postal, repère les tournois présents sur les deux sites (même jour, moins de 10 km,
noms proches) et écrit `data/events.json` ainsi que `site/events.js`.

## Utilisation

```bash
./update.sh                 # collecte + fusion (quelques minutes)
python3 -m http.server 8040 -d site   # puis http://localhost:8040
```

Ouvrir `site/index.html` directement dans un navigateur fonctionne aussi.

Options utiles :

```bash
python3 scrape_bcp.py --start 2024-01-01 --end 2027-12-31   # fenêtre de dates BCP
python3 scrape_mhq.py --refresh                              # re-télécharge tous les détails
python3 scrape_mhq.py --game 2                               # autre jeu (2 = Age of Sigmar…)
```

## Site

- Carte Leaflet (tuiles OpenStreetMap) avec regroupement des marqueurs ; couleur
  par source, marqueurs gris pour les tournois passés.
- Liste « À venir » / « Passés », clic sur une ligne pour centrer la carte.
- Filtres : recherche texte, période, dates, région, source, format, nombre de
  joueurs minimum, tri par date ou par distance (géolocalisation ou Maj + clic
  sur la carte). Les filtres sont encodés dans l'URL (`#…`) pour être partagés.

## Fichiers

```
scrape_bcp.py   scrape_mhq.py   build.py   update.sh   serve.sh (serveur local + ngrok)
data/bcp.json   data/mhq.json   data/events.json
site/index.html site/events.js
cache/mhq/      (pages de détail MiniHeadQuarters, une par tournoi ; ignoré par git)
.github/workflows/update.yml   (mise à jour hebdomadaire + déploiement Pages)
```
