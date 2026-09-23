"""Seconde source : contours des communes (API Geo, Etalab) et rattachement point -> commune.

GBIF ne fournit le decoupage administratif (GADM) que jusqu'a l'arrondissement.
Pour repondre a la question "quelles communes ont vu leurs premieres observations",
on telecharge les contours officiels des communes de la region et on rattache
chaque point par un test point-dans-polygone (sans dependance geospatiale lourde).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from collect import http_get
from config import project_path

log = logging.getLogger("reference")


@dataclass(frozen=True)
class Commune:
    code: str
    nom: str
    departement: str
    bbox: tuple[float, float, float, float]      # min_lon, min_lat, max_lon, max_lat
    polygons: tuple                               # liste de polygones, chacun = [anneau ext, trous...]


def fetch_communes(cfg: dict, source_cfg: dict, force: bool = False) -> Path:
    """Telecharge le GeoJSON des communes si le cache est absent ou trop ancien."""
    cache = project_path(cfg["cache_file"])
    if cache.exists() and not force:
        age_days = (time.time() - cache.stat().st_mtime) / 86400
        if age_days <= cfg["max_age_days"]:
            log.info("Referentiel communes en cache (%.0f jours) : %s", age_days, cache)
            return cache
    log.info("Telechargement du referentiel communes depuis %s", cfg["url"])
    response = http_get(cfg["url"], cfg["params"], source_cfg)
    tmp = cache.with_suffix(".tmp")
    tmp.write_bytes(response.content)
    tmp.replace(cache)
    return cache


def fetch_dataset_metadata(dataset_keys: list[str], cache_file: Path, source_cfg: dict) -> dict:
    """Titre, DOI et licence de chaque jeu de donnees : necessaire pour l'attribution CC BY."""
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    missing = [k for k in dataset_keys if k and k not in cache]
    for key in missing:
        meta = http_get(f"https://api.gbif.org/v1/dataset/{key}", {}, source_cfg).json()
        cache[key] = {
            "title": meta.get("title"),
            "doi": meta.get("doi"),
            "license": meta.get("license"),
            "publishing_org_key": meta.get("publishingOrganizationKey"),
        }
    if missing:
        log.info("Metadonnees de %s jeux de donnees telechargees", len(missing))
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return cache


def _ring_bbox(ring):
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def load_communes(path: Path) -> list[Commune]:
    data = json.loads(path.read_text(encoding="utf-8"))
    communes = []
    for feature in data["features"]:
        geom = feature["geometry"]
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        boxes = [_ring_bbox(poly[0]) for poly in polys]
        bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))
        props = feature["properties"]
        communes.append(Commune(props["code"], props["nom"], props["codeDepartement"], bbox, tuple(polys)))
    log.info("%s communes chargees", len(communes))
    return communes


def _point_in_ring(lon: float, lat: float, ring) -> bool:
    """Algorithme du lancer de rayon (ray casting)."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _point_in_polygon(lon: float, lat: float, polygon) -> bool:
    if not _point_in_ring(lon, lat, polygon[0]):
        return False
    return not any(_point_in_ring(lon, lat, hole) for hole in polygon[1:])


class CommuneLocator:
    """Rattache un point (lon, lat) a une commune, avec un filtre par emprise."""

    def __init__(self, communes: list[Commune]):
        self.communes = communes

    def locate(self, lon: float, lat: float) -> Commune | None:
        for commune in self.communes:
            min_lon, min_lat, max_lon, max_lat = commune.bbox
            if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
                continue
            if any(_point_in_polygon(lon, lat, poly) for poly in commune.polygons):
                return commune
        return None
