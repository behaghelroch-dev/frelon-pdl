"""Produit data/raw/sample_source.json : extrait versionnable de la zone raw.

La zone raw complete n'est pas versionnee (elle contient des noms d'observateurs).
L'echantillon garde la structure exacte de la reponse GBIF, mais les champs
personnels sont masques et les medias (qui citent leurs auteurs) retires.
"""
from __future__ import annotations

import json

from config import project_path
from extract import PERSONAL_FIELDS, latest_run_dir

MASK = "[SUPPRIME-RGPD]"
SAMPLE_SIZE = 25


def main() -> None:
    raw_dir = project_path("data/raw/x").parent
    run = latest_run_dir(raw_dir)
    page = sorted(run.glob("page_year-2025_*.json"))[0]
    payload = json.loads(page.read_text(encoding="utf-8"))
    records = payload["results"][:SAMPLE_SIZE]
    for rec in records:
        for field in PERSONAL_FIELDS:
            if field in rec:
                rec[field] = MASK
        rec.pop("extensions", None)
        rec.pop("media", None)
    payload["results"] = records
    payload["_sample_note"] = (
        f"Extrait de {run.name}/{page.name} ({SAMPLE_SIZE} premieres lignes). "
        "Champs personnels masques, medias retires. Structure GBIF inchangee."
    )
    out = raw_dir / "sample_source.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Echantillon ecrit : {out}")


if __name__ == "__main__":
    main()
