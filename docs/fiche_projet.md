# Fiche projet — FrelonWatch PDL (livrables de la séance 1)

## Pitch

Le frelon asiatique (*Vespa velutina*), arrivé en France en 2004, décime les ruchers de l'Ouest.
FrelonWatch PDL collecte les signalements publics de l'espèce dans les Pays de la Loire depuis GBIF.
Il les nettoie, les déduplique entre plateformes, les rattache à une commune, et indique où l'espèce
est apparue récemment et à quelle vitesse elle progresse. L'objectif est d'aider un apiculteur ou un
groupement de défense sanitaire (GDS) à placer ses pièges à fondatrices au printemps.

## Étape 1 — Définir l'application

| Question | Réponse |
|---|---|
| Nom provisoire | FrelonWatch PDL |
| Utilisateur | Apiculteur ou technicien d'un groupement de défense sanitaire apicole (GDSA) des Pays de la Loire |
| Problème | Les signalements sont éparpillés entre plusieurs plateformes (iNaturalist, INPN, CardObs, Observation.org…), sont souvent en double et ne sont pas rattachés aux communes. |
| Décision | Choisir, avant la saison, les communes où poser en priorité les pièges de printemps (février à mai) et où alerter les apiculteurs. |
| Question centrale | À quelle vitesse le frelon asiatique progresse-t-il dans les Pays de la Loire, et quelles communes ont vu leurs premières observations récemment ? |
| Périmètre | Inclus : *Vespa velutina* (espèce et sous-espèce *nigrithorax*), observations de présence, région Pays de la Loire (5 départements), depuis 2004. Exclus : autres frelons (*Vespa crabro*), données d'absence, nids détruits non publiés sur GBIF, données sans date exploitable. |
| Fréquence utile | Hebdomadaire en saison (les plateformes publient vers GBIF avec un délai de quelques jours à quelques semaines), et une analyse annuelle avant le printemps. |

## Étape 2 — Cas d'usage et KPI

1. En tant qu'apiculteur, je veux connaître les communes où le frelon a été observé pour la première fois
   ces 12 derniers mois, afin d'y renforcer le piégeage de printemps.
2. En tant que GDSA, je veux suivre le nombre cumulé de communes colonisées par année, afin de mesurer
   la vitesse de progression et de justifier des moyens de lutte.
3. En tant qu'apiculteur, je veux savoir quelles communes proches ont des observations printanières
   (fondatrices), afin de placer les pièges au bon moment et au bon endroit.

| Cas d'usage | KPI | Données nécessaires | Fréquence |
|---|---|---|---|
| Cas 1 : nouvelles communes | Nombre de communes nouvellement colonisées sur 12 mois glissants (8 au 23/09/2026) | date, commune INSEE, première observation par commune | Hebdomadaire |
| Cas 2 : vitesse de progression | Nouvelles communes par an et cumul (17 en 2025 ; 453 au total) | année, commune, dédoublonnage | Annuelle |
| Cas 3 : piégeage de printemps | Nombre d'observations « printemps_fondatrices » (février à mai) par commune | mois fiable (précision ≤ 31 j), commune | Annuelle, avant février |

## Étape 4 — Grain et dictionnaire

**Une ligne représente un signalement de présence du frelon asiatique en un lieu (arrondi à environ 100 m)
à une date donnée, toutes sources GBIF confondues.**

Clé métier : `observation_key` = hash de (espèce, jour, latitude à 3 décimales, longitude à 3 décimales).
Les signalements d'un même jour et d'un même point publiés par plusieurs plateformes forment une seule ligne.

| Champ | Type | Obligatoire | Description | Exemple |
|---|---|---|---|---|
| observation_key | string | Oui | Clé métier (hash SHA-1 tronqué) | `3f9a0c1b7e2d4a55` |
| gbif_id | integer | Oui | Identifiant GBIF de l'enregistrement conservé | 4923800752 |
| observed_date | date | Oui | Jour de l'observation | 2025-09-14 |
| observed_at_utc | datetime | Non | Horodatage UTC si l'heure est connue | 2020-11-08T12:51:31Z |
| date_precision_days | integer | Oui | 1 = jour exact, 365 = année seule | 1 |
| bio_phase | string | Non | Phase du cycle de la colonie | printemps_fondatrices |
| latitude / longitude | number | Oui | WGS84, arrondies à 3 décimales | 47.253 / -1.559 |
| coordinate_uncertainty_m | number | Non | Incertitude de localisation | 20 |
| commune_insee / commune_nom | string | Oui | Commune (API Géo) | 44109 / Nantes |
| departement_code | string | Oui | 44, 49, 53, 72 ou 85 | 44 |
| source_channel | string | Oui | Plateforme d'origine normalisée | iNaturalist |
| license_code | string | Oui | CC0_1_0, CC_BY_4_0 ou CC_BY_NC_4_0 | CC_BY_4_0 |
| n_source_records | integer | Oui | Nombre d'enregistrements fusionnés | 2 |
| is_first_in_commune | boolean | Oui | Première observation connue dans la commune | true |

Le dictionnaire complet (31 champs) se trouve dans [`config/data_contract.yaml`](../config/data_contract.yaml).

## Étapes 5 et 6 — Architecture et contrat

- Diagramme : [`docs/architecture.png`](architecture.png) (généré par `docs/make_architecture.py`)
- Contrat de données v1.0 : [`config/data_contract.yaml`](../config/data_contract.yaml)

## Étape 7 — Première collecte

Collecte du 23/09/2026 : `data/raw/gbif_20260923T081211Z/`, soit 24 pages JSON non modifiées et un
`manifest.json`, pour 1 750 observations reçues. Un extrait sans données personnelles est versionné
dans `data/raw/sample_source.json`.
