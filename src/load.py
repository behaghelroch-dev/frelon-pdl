"""Chargement SQLite idempotent : cle primaire metier + UPSERT."""
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


def _ddl() -> str:
    cols = []
    for col in CURATED_COLUMNS:
        if col == "observation_key":
            cols.append("observation_key TEXT PRIMARY KEY")
        elif col == "gbif_id":
            cols.append("gbif_id INTEGER NOT NULL UNIQUE")
        else:
            cols.append(f"{col} {_sql_type(col)}")
    return f"CREATE TABLE IF NOT EXISTS observations ({', '.join(cols)})"


def _to_python(value):
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def upsert_observations(curated: pd.DataFrame, db_path: Path) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cols = CURATED_COLUMNS
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "observation_key")
    sql = (f"INSERT INTO observations ({', '.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT(observation_key) DO UPDATE SET {updates}")
    rows = [tuple(_to_python(v) for v in rec) for rec in curated[cols].itertuples(index=False, name=None)]

    with sqlite3.connect(db_path) as conn:
        conn.execute(_ddl())
        before = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        conn.executemany(sql, rows)
        after = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    return {"rows_before": before, "rows_after": after, "inserted": after - before,
            "updated_or_unchanged": len(rows) - (after - before)}


def replace_table(df: pd.DataFrame, table: str, db_path: Path) -> None:
    """Tables d'indicateurs : recalculees entierement a chaque execution (remplacement controle)."""
    with sqlite3.connect(db_path) as conn:
        df.to_sql(table, conn, if_exists="replace", index=False)
