# ADR-002 : stocker le curated en CSV + SQLite

- **Statut** : acceptée
- **Date** : 23/09/2026

## Contexte

Le volume est faible : environ 1 800 observations brutes, 1 500 curated et 450 communes. L'utilisateur
(un apiculteur ou un technicien de GDSA) n'a pas de serveur et utilise un tableur. Le projet doit pouvoir
être exécuté par une autre personne **sans installer ni configurer de service**, et rejoué sans créer
de doublons.

## Décision

Organiser le stockage en zones de fichiers locaux :

| Zone | Format | Rôle |
|---|---|---|
| `data/raw/` | Pages JSON brutes + `manifest.json` | Copie exacte de la source, traçabilité (non versionnée, RGPD) |
| `data/rejected/` | CSV | Lignes rejetées avec la cause |
| `data/curated/` | CSV (écriture atomique) | Livrables lisibles dans un tableur |
| `data/curated/frelon_pdl.sqlite` | SQLite | Base interrogeable en SQL, historisée, chargée par UPSERT |

## Alternatives considérées

| Alternative | Pourquoi elle est écartée |
|---|---|
| PostgreSQL / PostGIS | Puissant pour le spatial, mais impose un serveur, des identifiants et une installation ; disproportionné pour quelques milliers de lignes |
| CSV seuls | Pas de contrainte d'unicité ni d'historique ; le rejeu repose uniquement sur le remplacement des fichiers |
| DuckDB / Parquet | Adapté à l'analytique en volume, mais moins familier pour l'utilisateur, et sans bénéfice à cette échelle |

## Conséquences

- ✅ Zéro installation : SQLite est inclus dans Python, et le projet s'exécute avec `pip install -r requirements.txt`.
- ✅ Les contraintes `PRIMARY KEY (observation_key)` et `UNIQUE (gbif_id)` garantissent l'unicité en
  base ; l'UPSERT rend le chargement idempotent.
- ✅ Les CSV s'ouvrent directement dans un tableur, et l'écriture atomique (fichier temporaire puis
  remplacement) évite un fichier à moitié écrit en cas d'arrêt.
- ⚠️ Pas d'accès concurrent ni multi-utilisateur : c'est acceptable pour un batch hebdomadaire
  mono-poste.
- ⚠️ Le rattachement à une commune (point dans un polygone) est codé en Python plutôt que confié à
  PostGIS, ce qui suffit pour 1 228 communes. En cas de passage à l'échelle nationale (35 000
  communes), PostGIS deviendrait pertinent.
