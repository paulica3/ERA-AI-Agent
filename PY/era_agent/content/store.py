"""Durable storage for the firm's track record (projects.json).

All persistent files live under ERA_DATA_DIR (default: PY/data), which in
production points at the Railway volume mounted at /data, so edits survive
redeploys. Writes are atomic (temp file + os.replace) and every save also drops
a timestamped backup under <data>/backups/ — cheap insurance given the volume's
ample free space.

This module is the single access point for the data; callers never touch the
JSON directly. If we ever outgrow a flat file, only this module changes.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from era_agent.content.schema import (
    CATEGORIES, CATEGORY_IDS, Project, empty_db, _now,
)

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"

# Committed seed shipped in the image; used to bootstrap an empty volume on the
# first run (and as the source of truth for local dev). PY/data is gitignored.
SEED_PATH = Path(__file__).resolve().parent / "projects.seed.json"


def data_dir() -> Path:
    return Path(os.getenv("ERA_DATA_DIR", str(_DEFAULT_DATA_DIR)))


def _projects_path() -> Path:
    return data_dir() / "projects.json"


def _backups_dir() -> Path:
    return data_dir() / "backups"


# ── Read ──────────────────────────────────────────────────────────────────────

def load_db() -> dict:
    """Return the full store, or a fresh skeleton (15 categories) if none exists."""
    p = _projects_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # Volume empty (or first boot) -> fall back to the committed seed.
        try:
            data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return empty_db()
    # Always refresh the category list from code (names/order are not user-editable).
    data["categories"] = CATEGORIES
    data.setdefault("projects", [])
    data.setdefault("version", 1)
    return data


def list_projects(category: str | None = None, active_only: bool = False) -> list[dict]:
    projects = load_db()["projects"]
    if category is not None:
        projects = [p for p in projects if p.get("category") == category]
    if active_only:
        projects = [p for p in projects if p.get("active", True)]
    return sorted(projects, key=lambda p: (p.get("category", ""), p.get("order", 0)))


# ── Write ─────────────────────────────────────────────────────────────────────

def save_db(data: dict) -> dict:
    """Validate and persist the store atomically, keeping a backup."""
    for proj in data.get("projects", []):
        if proj.get("category") not in CATEGORY_IDS:
            raise ValueError(f"Unknown category: {proj.get('category')!r}")

    payload = {
        "version": data.get("version", 1),
        "categories": CATEGORIES,
        "projects": data.get("projects", []),
    }

    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    target = _projects_path()

    # Backup the previous version before overwriting.
    if target.exists():
        _backups_dir().mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(target, _backups_dir() / f"projects-{ts}.json")

    # Atomic write: temp file in the same dir, then replace.
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return payload


def replace_projects(projects: list[dict]) -> dict:
    """Overwrite the whole project list (used by migration / bulk import)."""
    db = load_db()
    db["projects"] = projects
    return save_db(db)
