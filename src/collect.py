"""Collecteur GBIF : pagination par annee, reponses brutes conservees telles quelles.

Chaque execution cree un dossier data/raw/gbif_<horodatage>/ contenant :
  - une page JSON par appel API, strictement identique a la reponse recue ;
  - un manifest.json qui trace les parametres, les comptes et les controles.

Usage : python src/collect.py [--years 2023,2024]
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import load_config, project_path

log = logging.getLogger("collect")

SPECIES_MATCH_URL = "https://api.gbif.org/v1/species/match"


class CollectError(RuntimeError):
    """Erreur d'acces a la source, apres epuisement des relances."""


def http_get(url: str, params: dict, cfg: dict) -> requests.Response:
    """GET avec relances exponentielles sur erreurs reseau, 429 et 5xx."""
    retries = cfg["max_retries"]
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, params=params, timeout=cfg["timeout_seconds"])
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
            response.raise_for_status()
            return response
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            status = getattr(exc.response, "status_code", None) if isinstance(exc, requests.HTTPError) else None
            # Une erreur 4xx (hors 429) signale une requete invalide : inutile de relancer.
            if status is not None and 400 <= status < 500 and status != 429:
                raise CollectError(f"Requete refusee ({status}) : {url} {params}") from exc
            if attempt == retries:
                raise CollectError(f"Source indisponible apres {retries} tentatives : {exc}") from exc
            wait = cfg["backoff_seconds"] * 2 ** (attempt - 1)
            log.warning("Tentative %s/%s echouee (%s), nouvelle tentative dans %ss", attempt, retries, exc, wait)
            time.sleep(wait)
    raise AssertionError("unreachable")


def resolve_taxon_key(cfg: dict) -> int:
    """Verifie que le nom d'espece correspond toujours au taxonKey attendu."""
    response = http_get(SPECIES_MATCH_URL, {"name": cfg["species_name"]}, cfg)
    match = response.json()
    key = match.get("usageKey")
    if key is None or match.get("matchType") == "NONE":
        raise CollectError(f"Espece introuvable dans le referentiel GBIF : {cfg['species_name']}")
    if key != cfg["taxon_key"]:
        log.warning("taxonKey resolu (%s) different de la config (%s)", key, cfg["taxon_key"])
    return key


def year_chunks(cfg: dict, years: list[int] | None) -> list[str]:
    """Decoupe la collecte : un bloc historique puis une requete par annee.

    Le decoupage garantit que chaque requete reste sous le plafond de 100 000
    resultats et permet de relancer une seule annee en cas d'echec.
    """
    if years:
        return [str(y) for y in years]
    current_year = datetime.now(timezone.utc).year
    return [cfg["historical_range"]] + [str(y) for y in range(cfg["first_year"], current_year + 1)]


def collect_chunk(cfg: dict, taxon_key: int, year: str, run_dir: Path) -> dict:
    """Pagine une tranche d'annees et ecrit chaque page brute sur disque."""
    base_params = {
        "taxonKey": taxon_key,
        "gadmGid": cfg["gadm_gid"],
        "country": cfg["country"],
        "year": year,
        "limit": cfg["page_size"],
    }
    offset, pages, records, expected = 0, 0, 0, None
    while True:
        params = {**base_params, "offset": offset}
        response = http_get(cfg["base_url"], params, cfg)
        payload = response.json()
        if expected is None:
            expected = payload.get("count", 0)
            if expected > cfg["max_offset"]:
                raise CollectError(f"Tranche {year} trop volumineuse ({expected}) : redecouper par mois")

        page_file = run_dir / f"page_year-{year.replace(',', '-')}_offset-{offset:06d}.json"
        # On ecrit le texte recu, octet pour octet : c'est la copie brute non modifiee.
        page_file.write_bytes(response.content)

        n = len(payload.get("results", []))
        pages += 1
        records += n
        if payload.get("endOfRecords", True) or n == 0:
            break
        offset += cfg["page_size"]
        if offset >= cfg["max_offset"]:
            raise CollectError(f"Plafond de pagination atteint pour {year}")
        time.sleep(cfg["pause_between_pages"])

    log.info("Annee %-10s : %5s observations annoncees, %5s recues (%s pages)", year, expected, records, pages)
    return {"year": year, "expected": expected, "received": records, "pages": pages}


def total_count(cfg: dict, taxon_key: int) -> int:
    params = {"taxonKey": taxon_key, "gadmGid": cfg["gadm_gid"], "country": cfg["country"], "limit": 0}
    return http_get(cfg["base_url"], params, cfg).json()["count"]


def collect(config_path: str | None = None, years: list[int] | None = None) -> Path:
    full_cfg = load_config(config_path)
    cfg = full_cfg["source"]
    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    run_dir = project_path(full_cfg["paths"]["raw_dir"]) / f"gbif_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)

    taxon_key = resolve_taxon_key(cfg)
    chunks = [collect_chunk(cfg, taxon_key, y, run_dir) for y in year_chunks(cfg, years)]

    received = sum(c["received"] for c in chunks)
    announced_total = None if years else total_count(cfg, taxon_key)
    manifest = {
        "source": "GBIF occurrence search API",
        "source_url": cfg["base_url"],
        "licence_note": "Licence par enregistrement (CC0, CC BY 4.0, CC BY-NC 4.0) - voir champ license",
        "collected_at": started.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "duration_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
        "query": {"taxonKey": taxon_key, "gadmGid": cfg["gadm_gid"], "country": cfg["country"]},
        "chunks": chunks,
        "records_received": received,
        "records_announced_total": announced_total,
        # Les observations sans annee ne sont renvoyees par aucune tranche : on le signale.
        "records_without_year_estimate": None if announced_total is None else announced_total - received,
        "files": sorted(p.name for p in run_dir.glob("page_*.json")),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Collecte terminee : %s observations dans %s", received, run_dir)
    return run_dir


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Collecte GBIF des observations de frelon asiatique")
    parser.add_argument("--config", help="Chemin du fichier YAML de configuration")
    parser.add_argument("--years", help="Annees a collecter, separees par des virgules (ex : 2023,2024)")
    args = parser.parse_args()
    years = [int(y) for y in args.years.split(",")] if args.years else None
    try:
        collect(args.config, years)
    except CollectError as exc:
        log.error("%s", exc)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
