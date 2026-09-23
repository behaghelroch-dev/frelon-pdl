"""Regles de qualite automatisees.

Chaque regle possede un identifiant, une dimension, une condition lisible,
une action (REJETER, SIGNALER, ALERTER) et un compteur d'echecs.
Une ligne rejetee conserve la liste de toutes les regles qu'elle viole.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable

import pandas as pd

REJECT, FLAG, ALERT = "REJETER", "SIGNALER", "ALERTER"


@dataclass
class Rule:
    rule_id: str
    dimension: str
    condition: str
    action: str
    check: Callable[[pd.DataFrame, dict], pd.Series]   # renvoie True quand la ligne est VALIDE
    failures: int = field(default=0)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def check_coordinates(df, q):
    return df["latitude"].notna() & df["longitude"].notna()


def check_in_zone(df, q):
    b = q["bbox"]
    in_bbox = df["latitude"].between(b["min_lat"], b["max_lat"]) & df["longitude"].between(b["min_lon"], b["max_lon"])
    return in_bbox & df["commune_insee"].notna()


def check_date(df, q):
    start, end = df["date_start"], df["date_end"]
    today = pd.Timestamp(_today())
    return (
        start.notna()
        & (start.dt.year >= q["min_year"])
        & (end <= today)                       # pas de date dans le futur
        & (end >= start)
        & (df["date_precision_days"] <= 366)   # une periode de plusieurs annees est inexploitable
    )


def check_uncertainty(df, q):
    unc = df["coordinate_uncertainty_m"]
    return unc.isna() | ((unc >= 0) & (unc <= q["max_uncertainty_m"]))


def check_uncertainty_known(df, q):
    return df["coordinate_uncertainty_m"].notna()


def check_taxon(df, q):
    return (df["species_key"] == q["expected_species_key"]) & df["taxon_rank"].isin(q["accepted_ranks"])


def check_license(df, q):
    return df["license_code"].isin(q["allowed_licenses"])


def check_presence(df, q):
    return df["occurrence_status"].isin(q["accepted_occurrence_status"])


def build_rules() -> list[Rule]:
    return [
        Rule("Q01_coordonnees_presentes", "Completude",
             "latitude et longitude renseignees", REJECT, check_coordinates),
        Rule("Q02_dans_zone_etude", "Domaine",
             "point dans l'emprise regionale et dans une commune des Pays de la Loire", REJECT, check_in_zone),
        Rule("Q03_date_valide", "Validite",
             "date lisible, >= 2004, non future, precision <= 1 an", REJECT, check_date),
        Rule("Q04_incertitude_raisonnable", "Domaine",
             "incertitude de localisation <= max_uncertainty_m (ou inconnue)", REJECT, check_uncertainty),
        Rule("Q05_espece_et_rang", "Validite",
             "speciesKey = Vespa velutina et rang espece ou infra-specifique", REJECT, check_taxon),
        Rule("Q06_licence_autorisee", "Conformite",
             "licence dans CC0 / CC BY 4.0 / CC BY-NC 4.0", REJECT, check_license),
        Rule("Q07_presence_confirmee", "Coherence",
             "occurrenceStatus = PRESENT (pas de donnee d'absence)", REJECT, check_presence),
        Rule("Q08_incertitude_connue", "Completude",
             "incertitude de localisation renseignee", FLAG, check_uncertainty_known),
    ]


def apply_rules(df: pd.DataFrame, quality_cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, list[Rule]]:
    """Separe lignes acceptees et rejetees, avec la cause de rejet."""
    rules = build_rules()
    reasons = pd.Series([[] for _ in range(len(df))], index=df.index, dtype=object)
    flags = pd.Series([[] for _ in range(len(df))], index=df.index, dtype=object)
    for rule in rules:
        valid = rule.check(df, quality_cfg).fillna(False).astype(bool)
        failed = ~valid
        rule.failures = int(failed.sum())
        target = reasons if rule.action == REJECT else flags
        for idx in df.index[failed]:
            target.at[idx] = target.at[idx] + [rule.rule_id]

    out = df.copy()
    out["reject_reasons"] = reasons.map(";".join)
    out["quality_flags"] = flags.map(";".join)
    is_rejected = out["reject_reasons"] != ""
    return out.loc[~is_rejected].copy(), out.loc[is_rejected].copy(), rules


def check_freshness(curated: pd.DataFrame, quality_cfg: dict) -> dict:
    """Regle de fraicheur (ALERTER) : la derniere observation est-elle recente ?"""
    last = curated["observed_date"].max() if len(curated) else None
    age = None if last is None else (_today() - pd.Timestamp(last).date()).days
    ok = age is not None and age <= quality_cfg["freshness_max_days"]
    return {
        "rule_id": "Q10_fraicheur", "dimension": "Fraicheur",
        "condition": f"derniere observation datant de moins de {quality_cfg['freshness_max_days']} jours",
        "action": ALERT, "last_observation": None if last is None else str(last),
        "age_days": age, "failures": 0 if ok else 1,
    }


def check_personal_data_leak(raw: pd.DataFrame, published_texts: list[str], personal_fields: list[str]) -> dict:
    """Controle RGPD (ALERTER) : aucun nom d'observateur de la zone raw dans les sorties publiees.

    On ne teste que les valeurs assez specifiques (prenom + nom, ou >= 8 caracteres)
    pour eviter les faux positifs du type "Marie" dans "Sainte-Marie-du-Bois".
    Le rapport ne contient que le nombre de fuites, jamais les noms eux-memes.
    """
    names = set()
    for col in personal_fields:
        if col in raw:
            for value in raw[col].dropna().astype(str):
                value = value.strip()
                if " " in value or len(value) >= 8:
                    names.add(value)
    blob = "\n".join(published_texts)
    leaks = sum(1 for n in names if n in blob)
    return {
        "rule_id": "Q12_absence_donnees_personnelles", "dimension": "Conformite",
        "condition": "aucune valeur des champs personnels raw dans les fichiers curated / rejected",
        "action": ALERT, "values_checked": len(names), "failures": leaks,
    }


def check_collect_volume(manifest: dict) -> dict:
    """Controle de completude de la collecte (ALERTER) : recu == annonce par tranche."""
    gaps = [c for c in manifest.get("chunks", []) if c["expected"] != c["received"]]
    without_year = manifest.get("records_without_year_estimate") or 0
    return {
        "rule_id": "Q11_collecte_complete", "dimension": "Completude",
        "condition": "recu = annonce pour chaque tranche, et somme des tranches = total de la zone",
        "action": ALERT, "failures": len(gaps) + (1 if without_year > 0 else 0), "details": gaps,
        "records_without_year_not_collected": without_year,
    }
