# Évaluation des sources

Accès aux sources vérifié le 23/09/2026.

| Critère | Source A — GBIF (retenue) | Source B — API Géo (retenue, complément) | Source C — Plateforme « Frelon asiatique » / INPN (écartée) |
|---|---|---|---|
| Producteur et URL | Global Biodiversity Information Facility — `https://api.gbif.org/v1/occurrence/search` | Etalab / IGN / INSEE — `https://geo.api.gouv.fr/communes` | MNHN / PatriNat — `https://frelonasiatique.mnhn.fr`, `https://openobs.mnhn.fr` |
| Mode d'accès | API REST publique, pagination `limit`/`offset` | API REST publique | Consultation web, exports ponctuels |
| Format | JSON (Darwin Core) | GeoJSON | CSV à la demande, cartes |
| Fréquence de mise à jour | Continue (les jeux de données sont réindexés de quelques jours à quelques semaines) | Annuelle (code officiel géographique) | Continue |
| Clé ou identifiant | Aucune clé ; identifiant `gbifID` | Aucune clé ; code INSEE | Compte requis pour certains exports |
| Licence ou conditions | Licence par enregistrement : CC0 1.0 (10), CC BY 4.0 (906), CC BY-NC 4.0 (613) dans le curated | Licence Ouverte Etalab 2.0 | Conditions propres à chaque export |
| Risque technique | 300 résultats par page, plafond de 100 000 par requête ; `stateProvince` hétérogène ; données dupliquées entre plateformes | Fichier de 15 Mo ; contours INSEE et GADM légèrement différents | Pas d'API documentée stable, donc collecte non reproductible |
| Données personnelles | Oui : noms (`recordedBy`, `identifiedBy`, `rightsHolder`), pseudos, adresses (`verbatimLocality`) | Non | Oui |

## Pourquoi GBIF ?

- **Il répond directement à la question** : il agrège iNaturalist, CardObs, INPN Espèces, l'inventaire
  national Frelon du MNHN, Observation.org… en un seul point d'accès, filtrable par espèce
  (`taxonKey=1311477`) et par région (`gadmGid=FRA.12_1`).
- **L'accès est stable, documenté et autorisé** : API publique sans clé, sans scraping, respectueuse des
  conditions d'utilisation. Le collecteur marque une pause entre les pages.
- **Le volume est adapté** : 1 767 observations dans la région, soit environ 30 secondes de collecte.
- **La collecte est reproductible** : un autre étudiant obtient le même résultat avec
  `python src/pipeline.py --collect`.

Le filtre `gadmGid` a été préféré à `stateProvince`. Ce dernier est saisi librement par les fournisseurs
(« Pays de la Loire », « Nord (59) », anciennes régions…) et n'est donc pas fiable.

## Conformité et licences

- Le projet est pédagogique et **non commercial**, donc les trois licences (CC0, CC BY, CC BY-NC) sont
  compatibles. La règle **Q06** vérifie la licence de chaque ligne et rejette toute autre licence.
- **Attribution (CC BY)** : `data/curated/attributions.csv` liste chaque jeu de données utilisé avec son
  titre, son DOI, son lien GBIF et le nombre d'observations. Chaque ligne du curated porte aussi
  `license_code`, `attribution_required` et `non_commercial_only`, pour qu'un réutilisateur sache ce
  qu'il peut faire de chaque donnée.
- Citation GBIF recommandée : *GBIF.org (23 septembre 2026) GBIF Occurrence Search,
  taxonKey=1311477, gadmGid=FRA.12_1.* Pour une publication, il faudrait générer un téléchargement
  GBIF avec DOI (API `occurrence/download`, compte gratuit requis).

## Données personnelles (RGPD)

La zone raw contient les noms ou pseudonymes de 1 582 observateurs, ainsi que parfois une adresse.
Ces données ne servent pas à la question posée (principe de **minimisation**, art. 5.1.c RGPD) :

1. **Zone raw** : conservée intacte en local pour la traçabilité, mais **jamais versionnée**
   (`.gitignore`). L'échantillon versionné `sample_source.json` masque ces champs.
2. **Zones curated et rejected** : les colonnes `recordedBy`, `identifiedBy`, `rightsHolder`, `nick`,
   `verbatimLocality`, `locality`, `occurrenceRemarks`, `recordedByIDs` et `identifiedByIDs` sont
   supprimées.
3. **Titres de jeux de données** : certains contiennent un nom (« CardObs — Données naturalistes de
   X »). Le champ `source_channel` est donc une catégorie normalisée (« CardObs (INPN) »). Les titres
   complets n'apparaissent que dans `attributions.csv`, parce que la licence CC BY oblige à citer la
   source. Ce sont des métadonnées publiées volontairement par leur auteur.
4. **Généralisation spatiale** : coordonnées arrondies à 3 décimales (environ 100 m). Cela suffit pour
   une décision à l'échelle de la commune, et évite de publier l'emplacement exact d'un jardin privé.
5. Un contrôle automatique (voir README) vérifie qu'aucun nom de la zone raw n'apparaît dans les sorties.

L'espèce n'est pas protégée : c'est une espèce exotique envahissante réglementée. Publier la
localisation de ses observations ne crée aucun risque pour elle, contrairement à une espèce sensible
comme le loup.
