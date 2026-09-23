"""Chargement SQLite idempotent : cle primaire metier + UPSERT.

La table observations est historisee : une ligne absente du dernier snapshot
complet n'est pas supprimee mais marquee is_active = 0 (suppression logique).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from transform import CURATED_COLUMNS

INTEGER_COLS = {"gbif_id", "date_precision_days", "year", "month", "n_source_records", "n_source_datasets",
                "attribution_required", "non_commercial_only", "gbif_cluster_flag", "is_first_in_commune"}
REAL_COLS = {"latitude", "longitude", "coordinate_uncertainty_m"}


def _sql_type(col: str) -> str:
    return "INTEGER" if col in INTEGER_COLS else "REAL" if col in REAL_COLS else "TEXT"


# Colonnes propres a la base (hors contrat curated) : suivi des snapshots successifs.
TRACKING_COLS = {
    "is_active": "INTEGER NOT NULL DEFAULT 1",   # 1 si presente dans le dernier snapshot complet
    "first_seen_run": "TEXT",                    # collecte ou la ligne est apparue
    "last_seen_run": "TEXT",                     # derniere collecte qui la contenait
    "removed_at_run": "TEXT",                    # collecte ou elle a disparu de GBIF
}


def _ddl() -> str:
    cols = []
    for col in CURATED_COLUMNS:
        if col == "observation_key":
            cols.append("observation_key TEXT PRIMARY KEY")
        elif col == "gbif_id":
            cols.append("gbif_id INTEGER NOT NULL UNIQUE")
        else:
            cols.append(f"{col} {_sql_type(col)}")
    cols += [f"{c} {t}" for c, t in TRACKING_COLS.items()]
    return f"CREATE TABLE IF NOT EXISTS observations ({', '.join(cols)})"


def _migrate(conn: sqlite3.Connection) -> None:
    """Ajoute les colonnes de suivi a une base creee par une version anterieure."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(observations)")}
    for col, sql_type in TRACKING_COLS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE observations ADD COLUMN {col} {sql_type}")


def _to_python(value):
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def upsert_observations(curated: pd.DataFrame, db_path: Path, run_id: str | None = None,
                        full_snapshot: bool = False) -> dict:
    """UPSERT du snapshot curated, puis suppression logique des lignes disparues.

    full_snapshot doit etre vrai uniquement si la collecte est complete : sinon
    les observations non collectees seraient marquees supprimees a tort.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cols = CURATED_COLUMNS
    all_cols = cols + ["is_active", "first_seen_run", "last_seen_run", "removed_at_run"]
    placeholders = ", ".join("?" for _ in all_cols)
    updates = ", ".join(f"{c} = excluded.{c}" for c in all_cols
                        if c not in ("observation_key", "first_seen_run"))
    sql = (f"INSERT INTO observations ({', '.join(all_cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT(observation_key) DO UPDATE SET {updates}")
    rows = [tuple(_to_python(v) for v in rec) + (1, run_id, run_id, None)
            for rec in curated[cols].itertuples(index=False, name=None)]
    keys = [r[0] for r in rows]

    with sqlite3.connect(db_path) as conn:
        conn.execute(_ddl())
        _migrate(conn)
        conn.execute("CREATE TEMP TABLE snapshot (observation_key TEXT PRIMARY KEY, gbif_id INTEGER)")
        conn.executemany("INSERT INTO temp.snapshot VALUES (?, ?)",
                         zip(keys, (_to_python(v) for v in curated["gbif_id"])))
        before = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        reactivated = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE is_active = 0 "
            "AND observation_key IN (SELECT observation_key FROM temp.snapshot)").fetchone()[0]

        # Un gbif_id peut changer de cle metier (coordonnees ou date corrigees sur GBIF).
        # L'ancienne ligne, absente du snapshot, est remplacee par la nouvelle ; une ligne
        # encore presente libere temporairement son gbif_id (corrige par l'UPSERT).
        conflict = ("gbif_id IN (SELECT gbif_id FROM temp.snapshot) AND observation_key NOT IN "
                    "(SELECT observation_key FROM temp.snapshot s WHERE s.gbif_id = observations.gbif_id)")
        rekeyed = conn.execute(
            f"DELETE FROM observations WHERE {conflict} "
            "AND observation_key NOT IN (SELECT observation_key FROM temp.snapshot)").rowcount
        conn.execute(f"UPDATE observations SET gbif_id = -gbif_id WHERE {conflict}")

        after_cleanup = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        conn.executemany(sql, rows)
        after = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

        removed = 0
        if full_snapshot:
            removed = conn.execute(
                "UPDATE observations SET is_active = 0, removed_at_run = ? WHERE is_active = 1 "
                "AND observation_key NOT IN (SELECT observation_key FROM temp.snapshot)", (run_id,)).rowcount
        active = conn.execute("SELECT COUNT(*) FROM observations WHERE is_active = 1").fetchone()[0]
    return {"rows_before": before, "rows_after": after, "inserted": after - after_cleanup,
            "updated_or_unchanged": len(rows) - (after - after_cleanup),
            "rekeyed_replaced": rekeyed, "reactivated": reactivated,
            "snapshot_complete": full_snapshot, "marked_removed": removed, "active_rows": active}


def replace_table(df: pd.DataFrame, table: str, db_path: Path) -> None:
    """Tables d'indicateurs : recalculees entierement a chaque execution (remplacement controle)."""
    with sqlite3.connect(db_path) as conn:
        df.to_sql(table, conn, if_exists="replace", index=False)
