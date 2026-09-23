"""Pipeline batch FrelonWatch PDL : raw -> validation -> curated -> rapport.

Usage :
  python src/pipeline.py                 # traite la derniere collecte presente en zone raw
  python src/pipeline.py --collect       # collecte d'abord, puis traite
  python src/pipeline.py --demo-invalid  # ajoute des lignes volontairement invalides (demonstration)
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from collect import CollectError, collect
from config import load_config, project_path
from extract import latest_run_dir, read_run
from load import replace_table, upsert_observations
from profile_data import profile, write_profile
from reference import CommuneLocator, fetch_communes, fetch_dataset_metadata, load_communes
from transform import communes_first_seen, deduplicate, standardize, to_curated, yearly_progression
from validate import apply_rules, check_collect_volume, check_freshness, check_personal_data_leak

log = logging.getLogger("pipeline")

REJECTED_COLUMNS = [
    "gbif_id", "reject_reasons", "quality_flags", "dataset_key", "source_channel", "license_code",
    "taxon_rank", "species_key", "occurrence_status", "latitude", "longitude",
    "coordinate_uncertainty_m", "date_start", "date_end", "date_precision_days",
    "commune_insee", "source_file",
]


def demo_invalid_rows(raw: pd.DataFrame) -> pd.DataFrame:
    """Lignes synthetiques (gbifID negatifs) qui violent chacune une regle, plus un doublon."""
    # Base : une ligne reelle bien localisee, pour que chaque cas ne viole qu'une seule regle.
    precise = pd.to_numeric(raw["coordinateUncertaintyInMeters"], errors="coerce") <= 100
    base = raw[precise & (raw["eventDate"].astype(str).str.len() == 10)].iloc[0].to_dict()
    today = datetime.now(timezone.utc).date()
    cases = [
        {"decimalLatitude": None, "decimalLongitude": None},                        # Q01
        {"decimalLatitude": 48.8566, "decimalLongitude": 2.3522},                   # Q02 (Paris)
        {"eventDate": f"{today.year + 1}-05-01"},                                   # Q03 (futur)
        {"coordinateUncertaintyInMeters": 25000},                                   # Q04
        {"speciesKey": 1311334, "taxonRank": "GENUS"},                              # Q05
        {"license": "All rights reserved"},                                         # Q06
        {"occurrenceStatus": "ABSENT"},                                             # Q07
        {},                                                                         # doublon metier
    ]
    rows = []
    for i, overrides in enumerate(cases, start=1):
        row = {**base, **overrides, "gbifID": str(-i), "isInCluster": False,
               "source_file": "DEMO_SYNTHETIQUE"}
        rows.append(row)
    return pd.DataFrame(rows)


def write_csv_atomic(df: pd.DataFrame, path: Path) -> None:
    """Ecriture dans un fichier temporaire puis remplacement : jamais de fichier a moitie ecrit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8")
    tmp.replace(path)


def attributions(curated: pd.DataFrame, dataset_meta: dict) -> pd.DataFrame:
    counts = curated.groupby(["dataset_key", "license_code"]).size().rename("n_observations").reset_index()
    counts["dataset_title"] = counts["dataset_key"].map(lambda k: (dataset_meta.get(k) or {}).get("title"))
    counts["doi"] = counts["dataset_key"].map(lambda k: (dataset_meta.get(k) or {}).get("doi"))
    counts["gbif_url"] = "https://www.gbif.org/dataset/" + counts["dataset_key"]
    return counts.sort_values("n_observations", ascending=False)


def quality_status(curated_rows: int, rules, alerts) -> str:
    leak = next((a for a in alerts if a["rule_id"] == "Q12_absence_donnees_personnelles"), None)
    if curated_rows < 100 or (leak and leak["failures"]):
        return "FAIL"
    if any(a["failures"] for a in alerts) or any(r.failures for r in rules if r.action != "REJETER"):
        return "PASS_WITH_WARNINGS"
    return "PASS"


def run(config_path: str | None = None, run_dir: str | None = None,
        do_collect: bool = False, demo_invalid: bool = False) -> dict:
    t0 = time.perf_counter()
    cfg = load_config(config_path)
    paths, q = cfg["paths"], cfg["quality"]
    if demo_invalid:
        # La demonstration ecrit dans data/demo/ pour ne jamais polluer la zone curated ni la base.
        paths = {k: f"data/demo/{Path(v).name}" for k, v in paths.items() if k != "raw_dir"} | {
            "raw_dir": paths["raw_dir"]}
    executed_at = datetime.now(timezone.utc)

    if do_collect:
        run_path = collect(config_path)
    else:
        run_path = Path(run_dir) if run_dir else latest_run_dir(project_path(paths["raw_dir"]))

    # 1. Lecture raw + profilage initial
    raw, manifest = read_run(run_path)
    if demo_invalid:
        raw = pd.concat([raw, demo_invalid_rows(raw)], ignore_index=True)
        log.warning("Mode demonstration : lignes synthetiques invalides ajoutees, sorties dans data/demo/")
    reports_dir = project_path(paths["reports_dir"] + "/x").parent
    write_profile(profile(raw), reports_dir / "profile_raw.json")

    # 2. Referentiels (seconde source) + standardisation
    communes_file = fetch_communes(cfg["reference"], cfg["source"])
    locator = CommuneLocator(load_communes(communes_file))
    dataset_meta = fetch_dataset_metadata(
        sorted(raw["datasetKey"].dropna().unique()),
        project_path("data/reference/datasets_gbif.json"), cfg["source"])
    std = standardize(raw, locator, dataset_meta)

    # 3. Regles de qualite, separation acceptes / rejetes
    accepted, rejected, rules = apply_rules(std, q)

    # 4. Deduplication, pseudonymisation, zone curated
    deduped, dedup_stats = deduplicate(accepted, q["dedup_coord_decimals"])
    curated = to_curated(deduped, q["dedup_coord_decimals"])
    alerts = [check_freshness(curated, q), check_collect_volume(manifest)]

    # 5. Ecriture des zones curated / rejected (remplacement atomique = rejouable)
    curated_dir = project_path(paths["curated_dir"] + "/x").parent
    rejected_dir = project_path(paths["rejected_dir"] + "/x").parent
    communes_df = communes_first_seen(curated, executed_at.date())
    progression_df = yearly_progression(curated)
    write_csv_atomic(curated, curated_dir / "observations.csv")
    write_csv_atomic(communes_df, curated_dir / "communes_first_seen.csv")
    write_csv_atomic(progression_df, curated_dir / "progression_annuelle.csv")
    write_csv_atomic(attributions(curated, dataset_meta), curated_dir / "attributions.csv")
    write_csv_atomic(rejected[REJECTED_COLUMNS], rejected_dir / "rejected_rows.csv")

    published = [curated_dir / "observations.csv", curated_dir / "communes_first_seen.csv",
                 rejected_dir / "rejected_rows.csv"]
    alerts.append(check_personal_data_leak(
        raw, [p.read_text(encoding="utf-8") for p in published],
        # verbatimLocality est exclu : il contient souvent un simple nom de commune, publie par ailleurs.
        ["recordedBy", "identifiedBy", "rightsHolder", "http://unknown.org/nick"]))

    db_path = project_path(paths["database"])
    # Suppression logique uniquement si la collecte est complete (zone entiere, Q11 sans echec).
    q11 = next(a for a in alerts if a["rule_id"] == "Q11_collecte_complete")
    full_snapshot = manifest.get("records_announced_total") is not None and q11["failures"] == 0
    db_stats = upsert_observations(curated, db_path, run_path.name, full_snapshot)
    replace_table(communes_df, "communes_first_seen", db_path)
    replace_table(progression_df, "progression_annuelle", db_path)

    # 6. Rapport d'execution
    last_full_year = executed_at.year - 1
    prog = progression_df.set_index("year")
    recent = prog.loc[prog.index.isin(range(last_full_year - 4, last_full_year + 1)), "n_new_communes"]
    report = {
        "pipeline": "frelonwatch-pdl",
        "executed_at": executed_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_run": run_path.name,
        "source_collected_at": manifest.get("collected_at"),
        "demo_invalid_rows_injected": demo_invalid,
        "input_rows": int(len(raw)),
        "accepted_rows": int(len(accepted)),
        "rejected_rows": int(len(rejected)),
        "duplicates_removed": dedup_stats["technical_duplicates_removed"] + dedup_stats["business_duplicates_removed"],
        "curated_rows": int(len(curated)),
        "deduplication": dedup_stats,
        "quality_rules": [
            {"rule_id": r.rule_id, "dimension": r.dimension, "condition": r.condition,
             "action": r.action, "failures": r.failures} for r in rules
        ] + [{"rule_id": "Q09_unicite_cle_metier", "dimension": "Unicite",
              "condition": "cle (espece, jour, point arrondi a 100 m) unique",
              "action": "DEDUPLIQUER", "failures": dedup_stats["business_duplicates_removed"]}],
        "alerts": alerts,
        "personal_data": {
            "removed_columns": [c for c in std.columns if c.startswith("_pii_")],
            "rows_with_observer_name_in_raw": int(raw["recordedBy"].notna().sum()),
            "coordinates_generalised_to_decimals": q["dedup_coord_decimals"],
        },
        "kpi": {
            "communes_colonised_total": int(len(communes_df)),
            f"new_communes_{last_full_year}": int(prog["n_new_communes"].get(last_full_year, 0)),
            "new_communes_per_year_avg_last_5_years": round(float(recent.mean()), 1) if len(recent) else None,
            "communes_newly_colonised_last_12_months": int(communes_df["newly_colonised_last_12_months"].sum()),
        },
        "database": db_stats,
        "quality_status": quality_status(len(curated), rules, alerts),
        "duration_seconds": round(time.perf_counter() - t0, 2),
    }
    (reports_dir / "run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                                                 encoding="utf-8")
    history = reports_dir / "runs"
    history.mkdir(exist_ok=True)
    (history / f"run_{executed_at:%Y%m%dT%H%M%SZ}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log.info("Statut %s : %s lignes en entree, %s acceptees, %s rejetees, %s en curated (%ss)",
             report["quality_status"], report["input_rows"], report["accepted_rows"],
             report["rejected_rows"], report["curated_rows"], report["duration_seconds"])
    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Pipeline FrelonWatch Pays de la Loire")
    parser.add_argument("--config", help="Fichier YAML de configuration")
    parser.add_argument("--run-dir", help="Dossier raw a traiter (defaut : le plus recent)")
    parser.add_argument("--collect", action="store_true", help="Lancer une nouvelle collecte avant le traitement")
    parser.add_argument("--demo-invalid", action="store_true", help="Injecter des lignes invalides de demonstration")
    args = parser.parse_args()
    try:
        run(args.config, args.run_dir, args.collect, args.demo_invalid)
    except (CollectError, FileNotFoundError) as exc:
        log.error("%s", exc)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
