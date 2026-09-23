"""Genere docs/architecture.png (python docs/make_architecture.py)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

BOXES = {
    # nom: (x, y, largeur, hauteur, titre, detail, couleur)
    "gbif": (0.2, 4.2, 2.6, 1.3, "GBIF API", "proprietaire : GBIF\nCC0 / CC BY / CC BY-NC", "#dbe8f5"),
    "geo": (0.2, 1.6, 2.6, 1.3, "API Geo (Etalab)", "contours des communes\nLicence Ouverte 2.0", "#dbe8f5"),
    "collect": (3.6, 4.2, 2.6, 1.3, "Collecteur", "collect.py\npagination par annee\nrelances 429 / 5xx", "#fdebd0"),
    "raw": (7.0, 4.2, 2.6, 1.3, "Zone raw", "pages JSON non modifiees\n+ manifest.json horodate", "#eeeeee"),
    "ref": (3.6, 1.6, 2.6, 1.3, "Referentiels", "communes_pdl.geojson\nmetadonnees datasets", "#eeeeee"),
    "valid": (7.0, 1.6, 2.6, 1.3, "Validation", "validate.py\n11 regles de qualite", "#fdebd0"),
    "rejected": (7.0, -0.9, 2.6, 1.3, "Zone rejected", "rejected_rows.csv\n+ cause du rejet", "#f8d7da"),
    "curated": (10.4, 1.6, 2.6, 1.3, "Zone curated", "dedup + RGPD\nCSV + SQLite (UPSERT)", "#d4edda"),
    "app": (10.4, 4.2, 2.6, 1.3, "Restitution", "communes nouvellement\ncolonisees, progression", "#d4edda"),
    "report": (10.4, -0.9, 2.6, 1.3, "Rapport", "run_report.json\nprofile_raw.json", "#eeeeee"),
}
ARROWS = [("gbif", "collect"), ("collect", "raw"), ("geo", "ref"), ("raw", "valid"), ("ref", "valid"),
          ("valid", "rejected"), ("valid", "curated"), ("curated", "app"), ("curated", "report")]


def center(name, side):
    x, y, w, h, *_ = BOXES[name]
    return {"l": (x, y + h / 2), "r": (x + w, y + h / 2), "t": (x + w / 2, y + h), "b": (x + w / 2, y)}[side]


def sides(a, b):
    ax, ay, *_ = BOXES[a]
    bx, by, *_ = BOXES[b]
    if abs(ay - by) < 0.1:
        return ("r", "l") if bx > ax else ("l", "r")
    return ("b", "t") if by < ay else ("t", "b")


fig, ax = plt.subplots(figsize=(13, 7))
for name, (x, y, w, h, title, detail, color) in BOXES.items():
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05", fc=color, ec="#333333", lw=1.2))
    ax.text(x + w / 2, y + h - 0.28, title, ha="center", va="center", fontsize=11, weight="bold")
    ax.text(x + w / 2, y + h / 2 - 0.2, detail, ha="center", va="center", fontsize=8.5)
for a, b in ARROWS:
    sa, sb = sides(a, b)
    ax.add_patch(FancyArrowPatch(center(a, sa), center(b, sb), arrowstyle="-|>", mutation_scale=16,
                                 lw=1.4, color="#333333"))
ax.text(6.6, 6.2, "FrelonWatch PDL - architecture du pipeline batch (pipeline.py orchestre l'ensemble)",
        ha="center", fontsize=13, weight="bold")
ax.set_xlim(-0.2, 13.4)
ax.set_ylim(-1.2, 6.6)
ax.axis("off")
out = Path(__file__).with_name("architecture.png")
fig.savefig(out, dpi=150, bbox_inches="tight")
print(f"Schema ecrit : {out}")
