"""Standardisation, deduplication, pseudonymisation et indicateurs metier."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pandas as pd

from extract import PERSONAL_FIELDS
from reference import CommuneLocator

LICENSE_CODES = {
    "creativecommons.org/publicdomain/zero/1.0": "CC0_1_0",
    "creativecommons.org/licenses/by/4.0": "CC_BY_4_0",
    "creativecommons.org/licenses/by-nc/4.0": "CC_BY_NC_4_0",
}
# Ordre de preference lors de la deduplication : la licence la plus ouverte gagne.
LICENSE_PRIORITY = {"CC0_1_0": 0, "CC_BY_4_0": 1, "CC_BY_NC_4_0": 2}

LOCAL_TZ = "Europe/Paris"


# --------------------------------------------------------------------------- dates
def parse_event_date(value) -> tuple[pd.Timestamp | None, pd.Timestamp | None, pd.Timestamp | None]:
    """Renvoie (debut, fin, horodatage UTC si heure connue) pour un eventDate Darwin Core.

    Formats rencontres : 2020-11-08 ; 2020-11-08T13:51:31 ; 2014-01-01/2014-12-31 ; 2015.
    Une heure sans fuseau est une heure locale francaise : on la convertit en UTC.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == "":
        return None, None, None
    text = str(value).strip()
    start_txt, _, end_txt = text.partition("/")
    try:
        if len(start_txt) == 4 and start_txt.isdigit():          # annee seule
            start = pd.Timestamp(f"{start_txt}-01-01")
            end = pd.Timestamp(f"{start_txt}-12-31")
        else:
            start = pd.Timestamp(start_txt)
            end = pd.Timestamp(end_txt) if end_txt else start
    except (ValueError, TypeError):
        return None, None, None

    observed_utc = None
    if "T" in start_txt and not end_txt:
        observed_utc = start.tz_localize(LOCAL_TZ) if start.tzinfo is None else start
        observed_utc = observed_utc.tz_convert("UTC")
    start = start.tz_localize(None) if start.tzinfo else start
    end = end.tz_localize(None) if end.tzinfo else end
    return start.normalize(), end.normalize(), observed_utc


def license_code(url) -> str | None:
    if not isinstance(url, str):
        return None
    for fragment, code in LICENSE_CODES.items():
        if fragment in url:
            return code
    return "AUTRE"


# Canal de collecte normalise. On n'expose pas le titre brut du jeu de donnees :
# certains titres contiennent le nom d'une personne ("Donnees naturalistes de X").
CHANNEL_RULES = [
    ("inaturalist", "iNaturalist"),
    ("cardobs", "CardObs (INPN)"),
    ("inpn esp", "INPN Especes"),
    ("suivi de l'expansion du frelon", "Inventaire national Frelon (MNHN)"),
    ("patrinat", "Inventaire national Frelon (MNHN)"),
    ("observation.org", "Observation.org"),
    ("spipoll", "SPIPOLL"),
    ("lpo", "LPO"),
    ("onf", "ONF"),
]


def normalize_channel(label) -> str:
    text = str(label).lower() if isinstance(label, str) else ""
    for fragment, channel in CHANNEL_RULES:
        if fragment in text:
            return channel
    return "Autre inventaire" if text else "Inconnu"


def bio_phase(month) -> str | None:
    """Phase du cycle de la colonie, utile pour planifier le piegeage."""
    if pd.isna(month):
        return None
    m = int(month)
    if m in (2, 3, 4, 5):
        return "printemps_fondatrices"
    if m in (6, 7, 8):
        return "ete_ouvrieres"
    if m in (9, 10, 11):
        return "automne_reproduction"
    return "hiver_hivernage"


def precision_class(unc) -> str:
    if pd.isna(unc):
        return "inconnue"
    if unc <= 100:
        return "precise_100m"
    if unc <= 1000:
        return "moyenne_1km"
    return "faible_5km"


# --------------------------------------------------------------------------- standardisation
def standardize(raw: pd.DataFrame, locator: CommuneLocator, dataset_meta: dict) -> pd.DataFrame:
    """Type, renomme et enrichit les champs bruts. Ne supprime aucune ligne."""
    df = pd.DataFrame(index=raw.index)
    df["gbif_id"] = pd.to_numeric(raw["gbifID"], errors="coerce").astype("Int64")
    df["dataset_key"] = raw["datasetKey"]
    df["occurrence_status"] = raw["occurrenceStatus"]
    df["species_key"] = pd.to_numeric(raw["speciesKey"], errors="coerce").astype("Int64")
    df["taxon_name"] = raw["scientificName"]
    df["taxon_rank"] = raw["taxonRank"]
    df["basis_of_record"] = raw["basisOfRecord"]
    df["latitude"] = pd.to_numeric(raw["decimalLatitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(raw["decimalLongitude"], errors="coerce")
    df["coordinate_uncertainty_m"] = pd.to_numeric(raw["coordinateUncertaintyInMeters"], errors="coerce")
    df["license_code"] = raw["license"].map(license_code)
    df["gbif_cluster_flag"] = raw["isInCluster"].fillna(False).astype(bool)
    df["source_channel"] = (
        raw["institutionCode"].fillna(raw["datasetName"])
        .fillna(raw["datasetKey"].map(lambda k: (dataset_meta.get(k) or {}).get("title")))
        .map(normalize_channel)
    )

    parsed = raw["eventDate"].map(parse_event_date)
    df["date_start"] = pd.to_datetime(parsed.map(lambda t: t[0]))
    df["date_end"] = pd.to_datetime(parsed.map(lambda t: t[1]))
    df["observed_at_utc"] = parsed.map(lambda t: t[2].isoformat().replace("+00:00", "Z") if t[2] is not None else None)
    df["date_precision_days"] = (df["date_end"] - df["date_start"]).dt.days + 1

    communes = [
        locator.locate(lon, lat) if pd.notna(lat) and pd.notna(lon) else None
        for lat, lon in zip(df["latitude"], df["longitude"])
    ]
    df["commune_insee"] = [c.code if c else None for c in communes]
    df["commune_nom"] = [c.nom if c else None for c in communes]
    df["departement_code"] = [c.departement if c else None for c in communes]

    df["source_file"] = raw["source_file"]
    # Colonnes personnelles gardees uniquement jusqu'a la pseudonymisation (jamais publiees).
    for col in PERSONAL_FIELDS:
        df[f"_pii_{col}"] = raw[col]
    return df


# --------------------------------------------------------------------------- deduplication
def business_key(date_start, lat, lon, species_key, decimals: int) -> str:
    """Cle metier : meme espece, meme jour, meme point a ~100 m pres."""
    raw = f"{species_key}|{date_start:%Y-%m-%d}|{round(lat, decimals):.{decimals}f}|{round(lon, decimals):.{decimals}f}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def deduplicate(accepted: pd.DataFrame, decimals: int) -> tuple[pd.DataFrame, dict]:
    """Deux niveaux : identifiant technique GBIF puis cle metier inter-sources."""
    df = accepted.drop_duplicates(subset="gbif_id", keep="first").copy()
    technical = len(accepted) - len(df)

    df["observation_key"] = [
        business_key(d, la, lo, s, decimals)
        for d, la, lo, s in zip(df["date_start"], df["latitude"], df["longitude"], df["species_key"])
    ]
    # Ligne conservee : localisation la plus precise, puis licence la plus ouverte, puis plus petit id.
    df["_unc_sort"] = df["coordinate_uncertainty_m"].fillna(float("inf"))
    df["_lic_sort"] = df["license_code"].map(LICENSE_PRIORITY).fillna(9)
    df = df.sort_values(["observation_key", "_unc_sort", "_lic_sort", "gbif_id"])

    groups = df.groupby("observation_key")
    agg = pd.DataFrame({
        "n_source_records": groups.size(),
        "n_source_datasets": groups["dataset_key"].nunique(),
        "source_gbif_ids": groups["gbif_id"].agg(lambda s: ";".join(str(v) for v in sorted(s))),
        "any_cluster": groups["gbif_cluster_flag"].any(),
    })
    kept = df.drop_duplicates(subset="observation_key", keep="first").set_index("observation_key")
    kept = kept.drop(columns=["_unc_sort", "_lic_sort"]).join(agg).reset_index()

    cross = agg[agg["n_source_datasets"] > 1]
    stats = {
        "technical_duplicates_removed": int(technical),
        "business_duplicates_removed": int(len(df) - len(kept)),
        "duplicate_groups": int((agg["n_source_records"] > 1).sum()),
        "cross_dataset_groups": int(len(cross)),
        "cross_dataset_groups_confirmed_by_gbif_cluster": int(cross["any_cluster"].sum()),
    }
    return kept, stats


# --------------------------------------------------------------------------- zone curated
CURATED_COLUMNS = [
    "observation_key", "gbif_id", "observed_date", "observed_at_utc", "date_precision_days",
    "year", "month", "bio_phase", "latitude", "longitude", "coordinate_uncertainty_m",
    "precision_class", "commune_insee", "commune_nom", "departement_code",
    "taxon_name", "taxon_rank", "basis_of_record", "source_channel", "dataset_key",
    "license_code", "attribution_required", "non_commercial_only",
    "n_source_records", "n_source_datasets", "source_gbif_ids", "gbif_cluster_flag",
    "is_first_in_commune", "quality_flags", "source_file", "processed_at",
]


def drop_personal_data(df: pd.DataFrame) -> pd.DataFrame:
    """RGPD : suppression des noms, pseudos et adresses des observateurs (minimisation)."""
    return df.drop(columns=[c for c in df.columns if c.startswith("_pii_")])


def to_curated(deduped: pd.DataFrame, decimals: int) -> pd.DataFrame:
    df = drop_personal_data(deduped)
    df["observed_date"] = df["date_start"].dt.date
    df["year"] = df["date_start"].dt.year.astype("Int64")
    precise_month = df["date_precision_days"] <= 31
    df["month"] = df["date_start"].dt.month.where(precise_month).astype("Int64")
    df["bio_phase"] = df["month"].map(bio_phase)
    # Coordonnees generalisees a ~100 m : suffisant pour une decision a l'echelle communale,
    # et evite de publier la position exacte d'un jardin prive.
    df["latitude"] = df["latitude"].round(decimals)
    df["longitude"] = df["longitude"].round(decimals)
    df["precision_class"] = df["coordinate_uncertainty_m"].map(precision_class)
    df["attribution_required"] = df["license_code"] != "CC0_1_0"
    df["non_commercial_only"] = df["license_code"] == "CC_BY_NC_4_0"
    df["gbif_cluster_flag"] = df["any_cluster"]

    df = df.sort_values(["date_start", "observation_key"])
    first_idx = df.groupby("commune_insee")["date_start"].idxmin()
    df["is_first_in_commune"] = df.index.isin(first_idx)
    df["processed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return df[CURATED_COLUMNS].reset_index(drop=True)


# --------------------------------------------------------------------------- indicateurs
def communes_first_seen(curated: pd.DataFrame, reference_date) -> pd.DataFrame:
    """Une ligne par commune colonisee : premiere et derniere observation, pression recente."""
    ref = pd.Timestamp(reference_date)
    d = curated.assign(_date=pd.to_datetime(curated["observed_date"]))
    g = d.groupby(["commune_insee", "commune_nom", "departement_code"])
    out = pd.DataFrame({
        "first_observation_date": g["_date"].min().dt.date,
        "first_year": g["_date"].min().dt.year,
        "last_observation_date": g["_date"].max().dt.date,
        "n_observations": g.size(),
        "n_years_with_observation": g["year"].nunique(),
        "n_spring_observations": g["bio_phase"].agg(lambda s: int((s == "printemps_fondatrices").sum())),
        "n_observations_last_3_years": g["_date"].agg(lambda s: int((s >= ref - pd.DateOffset(years=3)).sum())),
    }).reset_index()
    first = pd.to_datetime(out["first_observation_date"])
    out["days_since_first_observation"] = (ref - first).dt.days
    out["newly_colonised_last_12_months"] = out["days_since_first_observation"] <= 365
    return out.sort_values("first_observation_date", ascending=False).reset_index(drop=True)


def yearly_progression(curated: pd.DataFrame) -> pd.DataFrame:
    """Vitesse de progression : nouvelles communes et cumul par annee."""
    first = curated[curated["is_first_in_commune"]].groupby("year").size()
    obs = curated.groupby("year").size()
    communes = curated.groupby("year")["commune_insee"].nunique()
    years = range(int(curated["year"].min()), int(curated["year"].max()) + 1)
    out = pd.DataFrame({"year": list(years)})
    out["n_observations"] = out["year"].map(obs).fillna(0).astype(int)
    out["n_communes_with_observation"] = out["year"].map(communes).fillna(0).astype(int)
    out["n_new_communes"] = out["year"].map(first).fillna(0).astype(int)
    out["cumulative_communes"] = out["n_new_communes"].cumsum()
    return out
