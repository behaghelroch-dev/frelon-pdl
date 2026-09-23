"""Lecture de la zone raw : aplatit les pages JSON GBIF en un DataFrame.

On ne garde ici que les champs utiles au contrat (plus les champs personnels,
conserves temporairement pour pouvoir prouver qu'ils sont bien supprimes ensuite).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger("extract")

# Champs GBIF (Darwin Core) lus depuis la zone raw.
RAW_FIELDS = [
    "gbifID", "datasetKey", "datasetName", "institutionCode", "publishingOrgKey",
    "basisOfRecord", "occurrenceStatus", "speciesKey", "scientificName", "taxonRank",
    "decimalLatitude", "decimalLongitude", "coordinateUncertaintyInMeters",
    "eventDate", "year", "month", "day", "license", "isInCluster", "issues",
    "individualCount", "lifeStage", "occurrenceID", "references",
]

# Champs contenant des donnees personnelles : lus pour le profilage RGPD, jamais publies.
PERSONAL_FIELDS = [
    "recordedBy", "identifiedBy", "rightsHolder", "http://unknown.org/nick",
    "verbatimLocality", "locality", "occurrenceRemarks", "recordedByIDs", "identifiedByIDs",
]


def latest_run_dir(raw_dir: Path) -> Path:
    runs = sorted(p for p in raw_dir.glob("gbif_*") if p.is_dir() and (p / "manifest.json").exists())
    if not runs:
        raise FileNotFoundError(f"Aucune collecte dans {raw_dir} : lancer d'abord src/collect.py")
    return runs[-1]


def _row(rec: dict, source_file: str) -> dict:
    row = {field: rec.get(field) for field in RAW_FIELDS + PERSONAL_FIELDS}
    gadm = rec.get("gadm") or {}
    row["gadm_level2"] = (gadm.get("level2") or {}).get("name")
    row["source_file"] = source_file
    return row


def read_run(run_dir: Path) -> tuple[pd.DataFrame, dict]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    records, seen = [], set()
    for page in sorted(run_dir.glob("page_*.json")):
        payload = json.loads(page.read_text(encoding="utf-8"))
        for rec in payload.get("results", []):
            records.append(_row(rec, f"{run_dir.name}/{page.name}"))
            seen.add(rec.get("gbifID"))
    # Balayage complementaire : seules les observations absentes des tranches
    # annuelles (sans annee exploitable) sont reprises.
    recovered = 0
    for page in sorted(run_dir.glob("scan_*.json")):
        payload = json.loads(page.read_text(encoding="utf-8"))
        for rec in payload.get("results", []):
            if rec.get("gbifID") not in seen:
                records.append(_row(rec, f"{run_dir.name}/{page.name}"))
                seen.add(rec.get("gbifID"))
                recovered += 1
    manifest["records_recovered_from_scan"] = recovered
    df = pd.DataFrame.from_records(records, columns=RAW_FIELDS + PERSONAL_FIELDS + ["gadm_level2", "source_file"])
    log.info("%s lignes lues depuis %s (dont %s issues du balayage complementaire)", len(df), run_dir, recovered)
    return df, manifest
