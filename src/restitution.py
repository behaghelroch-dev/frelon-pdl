"""Restitution visuelle : carte des communes colonisees et graphique de progression.

Les figures sont regenerees a chaque execution a partir des tables curated :
  - carte_communes.png : annee d'arrivee du frelon par commune, nouvelles communes en evidence ;
  - progression.png    : nouvelles communes par an et cumul (deux panneaux, un seul axe chacun).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import patheffects  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

log = logging.getLogger("restitution")

# Palette : rampe sequentielle bleue (une teinte, clair -> fonce) + un accent orange.
INK, INK_2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SURFACE, EMPTY = "#fcfcfb", "#f0efec"
ACCENT = "#eb6834"
PERIODS = [  # (premiere annee, derniere annee, couleur) : plus fonce = arrivee plus recente
    (2004, 2012, "#b7d3f6"),
    (2013, 2015, "#86b6ef"),
    (2016, 2018, "#5598e7"),
    (2019, 2021, "#256abf"),
    (2022, 2100, "#104281"),
]

plt.rcParams.update({"font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 9,
                     "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK_2,
                     "xtick.color": MUTED, "ytick.color": MUTED})


def _rings(geometry: dict) -> list:
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return [poly[0] for poly in polygons]  # contour exterieur uniquement


def _period_color(year: int) -> str:
    return next(color for start, end, color in PERIODS if start <= year <= end)


def _period_label(start: int, end: int, last_year: int) -> str:
    return f"{start}-{min(end, last_year)}" if start != 2004 else f"jusqu'à {end}"


def commune_map(communes: pd.DataFrame, communes_geojson: Path, out: Path) -> Path:
    features = json.loads(communes_geojson.read_text(encoding="utf-8"))["features"]
    first_year = dict(zip(communes["commune_insee"], communes["first_year"]))
    new = set(communes.loc[communes["newly_colonised_last_12_months"], "commune_insee"])

    polys, colors, centroids = [], [], {}
    for feat in features:
        code = feat["properties"]["code"]
        rings = _rings(feat["geometry"])
        year = first_year.get(code)
        color = EMPTY if year is None else ACCENT if code in new else _period_color(int(year))
        polys += rings
        colors += [color] * len(rings)
        main = max(rings, key=len)
        centroids[code] = (sum(p[0] for p in main) / len(main), sum(p[1] for p in main) / len(main))

    fig, ax = plt.subplots(figsize=(8.2, 7.2), facecolor=SURFACE)
    ax.add_collection(PolyCollection(polys, facecolors=colors, edgecolors="white", linewidths=0.25))
    ax.autoscale_view()
    ax.set_aspect(1 / 0.68)  # correction de la latitude (~47 deg N)
    ax.axis("off")

    # Etiquettes des nouvelles communes, decalees vers l'exterieur de la region.
    xmin, xmax = ax.get_xlim()
    xmid = (xmin + xmax) / 2
    for _, row in communes[communes["newly_colonised_last_12_months"]].iterrows():
        x, y = centroids[row["commune_insee"]]
        dx = 0.32 if x >= xmid else -0.32
        d = str(row["first_observation_date"])
        ax.annotate(f"{row['commune_nom']} ({d[5:7]}/{d[:4]})", xy=(x, y), xytext=(x + dx, y + 0.05),
                    fontsize=7.5, color=INK, ha="left" if dx > 0 else "right", va="center",
                    arrowprops={"arrowstyle": "-", "color": INK_2, "lw": 0.6},
                    path_effects=[patheffects.withStroke(linewidth=2.5, foreground="white")])

    last_year = int(communes["first_year"].max())
    handles = [Patch(fc=c, ec="none", label=_period_label(s, e, last_year)) for s, e, c in PERIODS]
    handles += [Patch(fc=ACCENT, ec="none", label="nouvelle commune (12 derniers mois)"),
                Patch(fc=EMPTY, ec="#c3c2b7", lw=0.5, label="aucune observation publiée")]
    ax.legend(handles=handles, title="Première observation", loc="upper left", frameon=False,
              fontsize=8, title_fontsize=8.5, labelcolor=INK_2)
    n_new = len(new)
    ax.set_title(f"Frelon asiatique en Pays de la Loire : {len(communes)} communes touchées, "
                 f"{n_new} nouvelles en 12 mois", loc="left", fontsize=11, color=INK, weight="bold")
    fig.text(0.02, 0.02, "Source : GBIF (observations), API Géo (contours). Une commune sans observation "
             "publiée n'est pas forcément indemne.", fontsize=7, color=MUTED)
    fig.savefig(out, dpi=160, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return out


def progression_chart(progression: pd.DataFrame, out: Path, current_year: int) -> Path:
    p = progression[progression["year"] >= 2008]
    fig, (left, right) = plt.subplots(1, 2, figsize=(10, 3.8), facecolor=SURFACE,
                                      gridspec_kw={"width_ratios": [1.35, 1]})
    for ax in (left, right):
        ax.set_facecolor(SURFACE)
        ax.grid(axis="y", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.tick_params(length=0)

    # Gauche : nouvelles communes par an (l'annee en cours est partielle).
    colors = ["#86b6ef" if y == current_year else "#2a78d6" for y in p["year"]]
    left.bar(p["year"], p["n_new_communes"], color=colors, width=0.72)
    left.set_title("Nouvelles communes touchées par an", loc="left", fontsize=10, color=INK, weight="bold")
    left.axvline(2018.5, color=INK_2, lw=0.8, ls=(0, (3, 3)))
    top = p["n_new_communes"].max()
    left.text(2018.7, top * 0.97, "après 2018 : moins de données\npubliées vers GBIF (biais)",
              fontsize=7.5, color=INK_2, va="top")
    for _, r in p[p["year"].isin([p.loc[p["n_new_communes"].idxmax(), "year"], current_year - 1])].iterrows():
        left.text(r["year"], r["n_new_communes"] + top * 0.02, str(r["n_new_communes"]),
                  ha="center", va="bottom", fontsize=8, color=INK)
    if current_year in set(p["year"]):
        left.text(current_year, p.loc[p["year"] == current_year, "n_new_communes"].iloc[0] + top * 0.02,
                  "en\ncours", ha="center", va="bottom", fontsize=6.5, color=MUTED)
    left.set_xticks([y for y in p["year"] if y % 2 == 0])

    # Droite : cumul des communes touchees.
    right.plot(p["year"], p["cumulative_communes"], color="#2a78d6", lw=2)
    last = p.iloc[-1]
    right.plot(last["year"], last["cumulative_communes"], "o", color="#2a78d6", ms=6,
               mec=SURFACE, mew=1.5)
    right.annotate(f"{last['cumulative_communes']} communes", (last["year"], last["cumulative_communes"]),
                   xytext=(-6, 8), textcoords="offset points", ha="right", fontsize=8.5, color=INK)
    right.set_title("Cumul des communes touchées", loc="left", fontsize=10, color=INK, weight="bold")
    right.set_ylim(0, last["cumulative_communes"] * 1.12)
    right.set_xticks([y for y in p["year"] if y % 4 == 0])

    fig.text(0.01, -0.02, "Source : GBIF, observations dédoublonnées et rattachées à une commune "
             "(première observation connue par commune).", fontsize=7, color=MUTED)
    fig.tight_layout()
    fig.savefig(out, dpi=160, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return out


def render(communes: pd.DataFrame, progression: pd.DataFrame, communes_geojson: Path,
           out_dir: Path, current_year: int) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = [commune_map(communes, communes_geojson, out_dir / "carte_communes.png"),
             progression_chart(progression, out_dir / "progression.png", current_year)]
    log.info("Figures ecrites dans %s", out_dir)
    return [str(f) for f in files]
