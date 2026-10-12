# ADR-003 : clé métier spatio-temporelle, UPSERT et suppression logique

- **Statut** : acceptée
- **Date** : 23/09/2026

## Contexte

Deux problèmes se posent :
1. **Doublons** : une même observation de frelon peut être publiée sur GBIF par plusieurs plateformes
   (par exemple iNaturalist et l'inventaire national), chacune avec son propre `gbifID`. Compter les
   deux fausserait le nombre d'observations, et parfois la date de première observation d'une commune.
2. **Évolution de la source** : entre deux collectes, GBIF ajoute des observations, en corrige
   (coordonnées, date) et en retire. Le pipeline est rejoué chaque semaine : il ne doit ni créer de
   doublons, ni perdre la trace de ce qui a disparu.

## Décision

- **Clé métier** `observation_key` = SHA-1 de (espèce, jour, latitude arrondie à 3 décimales,
  longitude arrondie à 3 décimales), soit environ 100 m. Les lignes de même clé sont fusionnées. On garde
  la localisation la plus précise, puis la licence la plus ouverte, et on conserve les identifiants
  fusionnés (`source_gbif_ids`, `n_source_records`).
- **Chargement SQLite par UPSERT** sur cette clé (`INSERT … ON CONFLICT DO UPDATE`).
- **Suppression logique** : une ligne absente d'une nouvelle collecte passe à `is_active = 0`, avec
  `removed_at_run` ; elle est réactivée si elle réapparaît. Ce marquage n'a lieu que si la collecte est
  **complète** (toute la zone, règle Q11 sans échec).
- Si un `gbif_id` change de clé (coordonnées corrigées), l'ancienne ligne est remplacée.

## Alternatives considérées

| Alternative | Pourquoi elle est écartée |
|---|---|
| Clé = `gbifID` seul | Ne détecte pas les doublons inter-plateformes, puisque chaque plateforme a son propre `gbifID` |
| Rapprochement flou (distance < 1 km, ±1 jour) | Risque de fusionner deux vraies observations voisines ; difficile à expliquer et à tester |
| Écraser la base à chaque exécution (`DROP` + `INSERT`) | Perd l'historique : impossible de savoir qu'une observation a été retirée de GBIF |
| `DELETE` physique des lignes disparues | Même perte d'information, et irréversible si une collecte est incomplète |

## Conséquences

- ✅ 109 doublons fusionnés, dont 20 groupes inter-plateformes, **tous confirmés** par l'algorithme de
  clustering de GBIF (`isInCluster`). C'est une validation indépendante de la clé.
- ✅ Rejeu idempotent : une seconde exécution donne `inserted: 0`.
- ✅ Historique exploitable : `SELECT * FROM observations WHERE is_active = 1` donne l'état courant, et
  `removed_at_run` date chaque disparition.
- ✅ Le garde-fou « collecte complète » empêche une collecte partielle (`--years`) de marquer des
  centaines de lignes comme supprimées.
- ⚠️ Deux plateformes qui arrondissent différemment la même observation (centroïde de commune contre
  point GPS) ne sont pas fusionnées. Piste : l'API de clustering GBIF (`/occurrence/{id}/experimental/related`).
- ⚠️ La base SQLite grossit avec l'historique ; c'est négligeable à cette échelle.
