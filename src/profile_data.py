"""Profilage initial des donnees brutes (etape 2 de la seance 2)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from extract import PERSONAL_FIELDS

CATEGORICAL = ["datasetName", "institutionCode", "basisOfRecord", "taxonRank", "license", "occurrenceStatus"]
NUMERIC = ["decimalLatitude", "decimalLongitude", "coordinateUncertaintyInMeters", "year", "month"]


def profile(df: pd.DataFrame) -> dict:
    hashable = df.drop(columns=["issues", "recordedByIDs", "identifiedByIDs"], errors="ignore")
    key_dups = df.assign(
        d=df["eventDate"].astype(str).str[:10],
        la=df["decimalLatitude"].round(3),
        lo=df["decimalLongitude"].round(3),
    ).duplicated(["d", "la", "lo"]).sum()
    return {
        "rows": int(df.shape[0]),
        "columns": int(df.shape[1]),
        "dtypes": {c: str(t) for c, t in df.dtypes.items()},
        "missing_rate": {c: round(float(v), 4) for c, v in df.isna().mean().sort_values(ascending=False).items()},
        "exact_duplicate_rows": int(hashable.drop(columns=["source_file"]).astype(str).duplicated().sum()),
        "duplicate_gbif_ids": int(df["gbifID"].duplicated().sum()),
        "duplicate_business_keys_date_point100m": int(key_dups),
        "in_gbif_cluster": int(df["isInCluster"].fillna(False).astype(bool).sum()),
        "numeric_ranges": {
            c: {"min": _num(df[c].min()), "max": _num(df[c].max())} for c in NUMERIC if c in df
        },
        "event_date_formats": df["eventDate"].astype(str).str.len().value_counts().to_dict(),
        "top_values": {c: df[c].fillna("<vide>").value_counts().head(5).to_dict() for c in CATEGORICAL},
        "personal_fields_filled": {c: int(df[c].notna().sum()) for c in PERSONAL_FIELDS if c in df},
    }


def _num(v):
    return None if pd.isna(v) else float(v)


def write_profile(report: dict, path: Path) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
