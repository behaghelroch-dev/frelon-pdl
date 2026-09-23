"""Tests unitaires : regles de qualite, dates, deduplication, RGPD, idempotence, pagination."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import collect  # noqa: E402
from config import load_config  # noqa: E402
from load import upsert_observations  # noqa: E402
from reference import Commune, CommuneLocator  # noqa: E402
from transform import (  # noqa: E402
    deduplicate, drop_personal_data, license_code, normalize_channel, parse_event_date, to_curated,
)
from extract import read_run  # noqa: E402
from validate import apply_rules, check_collect_volume  # noqa: E402

Q = load_config()["quality"]


def make_row(**overrides) -> dict:
    """Ligne standardisee valide ; chaque test en casse un seul champ."""
    row = {
        "gbif_id": 1, "dataset_key": "ds-a", "occurrence_status": "PRESENT", "species_key": 1311477,
        "taxon_name": "Vespa velutina", "taxon_rank": "SPECIES", "basis_of_record": "HUMAN_OBSERVATION",
        "latitude": 47.47, "longitude": -0.55, "coordinate_uncertainty_m": 20.0,
        "license_code": "CC_BY_4_0", "gbif_cluster_flag": False, "source_channel": "iNaturalist",
        "date_start": pd.Timestamp("2024-04-10"), "date_end": pd.Timestamp("2024-04-10"),
        "observed_at_utc": None, "date_precision_days": 1,
        "commune_insee": "49007", "commune_nom": "Angers", "departement_code": "49",
        "source_file": "test.json", "_pii_recordedBy": "Jean Dupont",
    }
    row.update(overrides)
    return row


def rejected_by(**overrides) -> str:
    df = pd.DataFrame([make_row(**overrides)])
    _, rejected, _ = apply_rules(df, Q)
    return rejected["reject_reasons"].iloc[0] if len(rejected) else ""


def test_valid_row_is_accepted():
    assert rejected_by() == ""


@pytest.mark.parametrize("overrides, rule", [
    ({"latitude": None, "longitude": None, "commune_insee": None}, "Q01_coordonnees_presentes"),
    ({"latitude": 48.85, "longitude": 2.35, "commune_insee": None}, "Q02_dans_zone_etude"),
    ({"date_start": pd.Timestamp("2099-01-01"), "date_end": pd.Timestamp("2099-01-01")}, "Q03_date_valide"),
    ({"date_start": pd.Timestamp("1998-06-01"), "date_end": pd.Timestamp("1998-06-01")}, "Q03_date_valide"),
    ({"date_start": pd.NaT, "date_end": pd.NaT, "date_precision_days": None}, "Q03_date_valide"),
    ({"date_start": pd.Timestamp("2014-01-01"), "date_end": pd.Timestamp("2016-12-31"),
      "date_precision_days": 1096}, "Q03_date_valide"),
    ({"coordinate_uncertainty_m": 25000.0}, "Q04_incertitude_raisonnable"),
    ({"species_key": 1311334, "taxon_rank": "GENUS"}, "Q05_espece_et_rang"),
    ({"license_code": "AUTRE"}, "Q06_licence_autorisee"),
    ({"occurrence_status": "ABSENT"}, "Q07_presence_confirmee"),
])
def test_each_rule_rejects_its_case(overrides, rule):
    assert rule in rejected_by(**overrides).split(";")


def test_missing_uncertainty_is_flagged_not_rejected():
    df = pd.DataFrame([make_row(coordinate_uncertainty_m=None)])
    accepted, rejected, _ = apply_rules(df, Q)
    assert len(rejected) == 0
    assert accepted["quality_flags"].iloc[0] == "Q08_incertitude_connue"


@pytest.mark.parametrize("value, start, end, precision, has_time", [
    ("2020-11-08", "2020-11-08", "2020-11-08", 1, False),
    ("2020-11-08T13:51:31", "2020-11-08", "2020-11-08", 1, True),
    ("2014-01-01/2014-12-31", "2014-01-01", "2014-12-31", 365, False),
    ("2015", "2015-01-01", "2015-12-31", 365, False),
])
def test_parse_event_date_formats(value, start, end, precision, has_time):
    s, e, utc = parse_event_date(value)
    assert str(s.date()) == start and str(e.date()) == end
    assert (e - s).days + 1 == precision
    assert (utc is not None) == has_time


def test_local_time_converted_to_utc():
    _, _, utc = parse_event_date("2020-07-01T14:00:00")   # heure d'ete : UTC+2
    assert utc.hour == 12 and str(utc.tz) == "UTC"


def test_parse_event_date_garbage():
    assert parse_event_date("pas une date") == (None, None, None)
    assert parse_event_date(None) == (None, None, None)


def test_license_mapping():
    assert license_code("http://creativecommons.org/licenses/by-nc/4.0/legalcode") == "CC_BY_NC_4_0"
    assert license_code("http://creativecommons.org/publicdomain/zero/1.0/legalcode") == "CC0_1_0"
    assert license_code("All rights reserved") == "AUTRE"


def test_cross_source_duplicate_is_merged_keeping_most_precise():
    df = pd.DataFrame([
        make_row(gbif_id=10, dataset_key="inaturalist", coordinate_uncertainty_m=3000.0),
        make_row(gbif_id=11, dataset_key="inpn", latitude=47.4702, coordinate_uncertainty_m=15.0),
        make_row(gbif_id=12, date_start=pd.Timestamp("2024-04-11"), date_end=pd.Timestamp("2024-04-11")),
    ])
    kept, stats = deduplicate(df, decimals=3)
    assert len(kept) == 2
    assert stats["business_duplicates_removed"] == 1 and stats["cross_dataset_groups"] == 1
    merged = kept[kept["n_source_records"] == 2].iloc[0]
    assert merged["gbif_id"] == 11 and merged["source_gbif_ids"] == "10;11"


def test_same_gbif_id_twice_counts_as_technical_duplicate():
    df = pd.DataFrame([make_row(gbif_id=5), make_row(gbif_id=5)])
    _, stats = deduplicate(df, decimals=3)
    assert stats["technical_duplicates_removed"] == 1


def test_personal_data_removed_from_curated():
    kept, _ = deduplicate(pd.DataFrame([make_row()]), decimals=3)
    kept["quality_flags"] = ""
    curated = to_curated(kept, decimals=3)
    assert not any(c.startswith("_pii_") for c in curated.columns)
    assert "Jean Dupont" not in curated.to_csv()
    assert drop_personal_data(pd.DataFrame([make_row()])).filter(like="_pii_").empty


def test_channel_does_not_expose_person_name_from_dataset_title():
    title = "CardObs : Observations naturalistes issues de l'outil CardObs-Donnees naturalistes de DUPONT Jean"
    assert normalize_channel(title) == "CardObs (INPN)"
    assert normalize_channel("Un inventaire local de DUPONT Jean") == "Autre inventaire"


def test_point_in_polygon_with_hole():
    square = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
    locator = CommuneLocator([Commune("00001", "Test", "00", (0, 0, 10, 10), ([square, hole],))])
    assert locator.locate(2, 2).code == "00001"
    assert locator.locate(5, 5) is None          # dans le trou
    assert locator.locate(12, 5) is None         # hors emprise


def test_upsert_is_idempotent(tmp_path):
    kept, _ = deduplicate(pd.DataFrame([make_row(gbif_id=1), make_row(gbif_id=2, latitude=47.0)]), 3)
    kept["quality_flags"] = ""
    curated = to_curated(kept, 3)
    db = tmp_path / "t.sqlite"
    first = upsert_observations(curated, db)
    second = upsert_observations(curated, db)
    assert first["inserted"] == 2
    assert second["inserted"] == 0 and second["rows_after"] == 2


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status
        self.content = json.dumps(payload).encode()

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


def test_collector_paginates_and_keeps_raw_pages(tmp_path, monkeypatch):
    total = 650
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params["offset"])
        n = min(params["limit"], total - params["offset"])
        results = [{"gbifID": str(params["offset"] + i)} for i in range(n)]
        return FakeResponse({"count": total, "results": results,
                             "endOfRecords": params["offset"] + n >= total})

    monkeypatch.setattr(collect.requests, "get", fake_get)
    cfg = load_config()["source"] | {"pause_between_pages": 0}
    stats = collect.collect_chunk(cfg, 1311477, "2024", tmp_path)
    assert calls == [0, 300, 600]
    assert stats["received"] == total and stats["pages"] == 3
    assert len(list(tmp_path.glob("page_*.json"))) == 3


def test_collector_retries_then_fails(monkeypatch):
    monkeypatch.setattr(collect.requests, "get", lambda *a, **k: FakeResponse({}, status=503))
    monkeypatch.setattr(collect.time, "sleep", lambda s: None)
    cfg = load_config()["source"]
    with pytest.raises(collect.CollectError):
        collect.http_get("https://example.org", {}, cfg)


def test_complement_scan_only_adds_records_missing_from_year_chunks(tmp_path):
    manifest = {"chunks": [{"year": "2024", "expected": 2, "received": 2}], "records_without_year_estimate": 1}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "page_year-2024_offset-000000.json").write_text(
        json.dumps({"results": [{"gbifID": "1", "year": 2024}, {"gbifID": "2", "year": 2024}]}), encoding="utf-8")
    (tmp_path / "scan_all_offset-000000.json").write_text(
        json.dumps({"results": [{"gbifID": "1"}, {"gbifID": "2"}, {"gbifID": "3", "eventDate": None}]}),
        encoding="utf-8")
    df, man = read_run(tmp_path)
    assert sorted(df["gbifID"]) == ["1", "2", "3"]
    assert man["records_recovered_from_scan"] == 1
    assert df.loc[df["gbifID"] == "3", "source_file"].iloc[0].endswith("scan_all_offset-000000.json")
    assert check_collect_volume(man)["failures"] == 0


def test_q11_alerts_when_records_without_year_not_recovered():
    manifest = {"chunks": [{"year": "2024", "expected": 5, "received": 5}],
                "records_without_year_estimate": 17, "records_recovered_from_scan": 0}
    alert = check_collect_volume(manifest)
    assert alert["failures"] == 1 and alert["records_without_year_not_collected"] == 17
