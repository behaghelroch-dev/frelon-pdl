# ADR-001 : collecter les observations via l'API GBIF

- **Statut** : acceptée
- **Date** : 23/09/2026

## Contexte

Le projet doit suivre l'arrivée du frelon asiatique commune par commune en Pays de la Loire. Les
signalements sont dispersés entre plusieurs plateformes : iNaturalist, CardObs, INPN Espèces,
l'inventaire national Frelon du MNHN, Observation.org… La collecte doit être **reproductible** par une
autre personne, **autorisée** (pas de scraping), et chaque donnée doit avoir une licence connue.

## Décision

Utiliser l'API publique **GBIF `occurrence/search`** comme source unique d'observations, filtrée par espèce
(`taxonKey=1311477`) et par région (`gadmGid=FRA.12_1`). Les contours des communes viennent de l'**API Géo**
(Etalab), utilisée comme référentiel d'enrichissement.

Détails de mise en œuvre :
- une requête par année, pour rester sous le plafond GBIF de 100 000 résultats par requête ;
- un balayage complémentaire sans filtre d'année pour les observations sans date exploitable, car GBIF
  ne permet pas de filtrer sur une année absente ;
- le filtre `gadmGid` plutôt que `stateProvince`, champ saisi librement et donc peu fiable (« Nord (59) »,
  anciennes régions…).

## Alternatives considérées

| Alternative | Pourquoi elle est écartée |
|---|---|
| Plateforme « Frelon asiatique » / OpenObs (MNHN) | Pas d'API documentée stable ; exports manuels, parfois avec compte ; collecte non reproductible |
| Interroger chaque plateforme séparément (API iNaturalist, CardObs…) | Plusieurs formats et authentifications à maintenir ; GBIF les agrège déjà au format Darwin Core |
| Scraper des cartes ou des sites de GDSA | Non autorisé par les conditions d'utilisation, et fragile |

## Conséquences

- ✅ Un seul point d'accès, sans clé, documenté ; environ 1 800 observations collectées en 30 secondes.
- ✅ Une licence par enregistrement (CC0, CC BY, CC BY-NC), contrôlée par la règle Q06 ; attribution
  dans `attributions.csv`.
- ⚠️ **Doublons inter-plateformes** : une même observation peut arriver par deux canaux. C'est traité
  par le dédoublonnage (ADR-003).
- ⚠️ **Biais de publication** : les signalements de terrain des GDSA ne sont pas sur GBIF, et
  l'inventaire national publie moins depuis 2018. Une absence d'observation ne prouve pas une absence
  de frelon. Cette limite est affichée sur la carte et dans le README.
- ⚠️ **Délai** : les plateformes publient vers GBIF avec un retard de quelques jours à quelques
  semaines. La règle Q10 (fraîcheur) le surveille.
