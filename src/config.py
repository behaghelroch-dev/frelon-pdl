"""Chargement de la configuration et chemins du projet."""
from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "pipeline.yaml"


def load_config(path: Path | str | None = None) -> dict:
    config_path = Path(path) if path else DEFAULT_CONFIG
    with open(config_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def project_path(relative: str) -> Path:
    """Resout un chemin de la config par rapport a la racine du projet."""
    path = PROJECT_ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
