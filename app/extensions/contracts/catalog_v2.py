# app/extensions/contracts/catalog_v2.py

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from flask import current_app

__all__ = [
    "SKU",
    "Substitution",
    "get_sku",
    "list_skus",
    "validate_sku",
    "list_substitutions",
    "cost_for",
]

# allow override via env
CATALOG_ENV = "VCDB_SKU_CATALOG"  # optional path override


@dataclass(frozen=True)
class SKU:
    code: str
    name: str
    classification_key: str  # Governance program key
    unit: str  # "kit", "each", "mile", etc.
    default_cost_cents: int
    version: int
    active: bool = True


@dataclass(frozen=True)
class Substitution:
    src_code: str
    alt_code: str
    priority: int  # 1 = preferred


def _catalog_path() -> Path:
    # default to repo-local data file
    app_root = Path(current_app.root_path)
    default_path = app_root / "slices" / "logistics" / "data" / "skus.json"
    override = os.getenv(CATALOG_ENV)
    return Path(override) if override else default_path


def _load_catalog() -> list[SKU]:
    p = _catalog_path()
    if not p.exists():
        # Developer-friendly fallback so CLI/tests aren’t blocked
        return [
            SKU(
                code="UG-TP-DR-M-OD-V-001",
                name="Uniform Top — Dress (Men, OD, Veteran)",
                classification_key="basic_needs.clothing.top",
                unit="each",
                default_cost_cents=0,
                version=1,
                active=True,
            ),
            SKU(
                code="HS-SL-DR-*-*-U-001",
                name="Sleeping Bag — Standard",
                classification_key="housing.sleeping_gear.bag",
                unit="kit",
                default_cost_cents=0,
                version=1,
                active=True,
            ),
        ]

    data = json.loads(p.read_text())
    out: list[SKU] = []
    for row in data:
        out.append(
            SKU(
                code=row["code"],
                name=row["name"],
                classification_key=row["classification_key"],
                unit=row["unit"],
                default_cost_cents=int(row["default_cost_cents"]),
                version=int(row.get("version", 1)),
                active=bool(row.get("active", True)),
            )
        )
    return out


def list_skus(active_only: bool = True) -> list[SKU]:
    """List SKUs from the registry. Provider: Logistics."""
    items = _load_catalog()
    return [s for s in items if (s.active or not active_only)]


# NOTE: These are *contracts*. Implementations live in owning slice (Logistics).


def get_sku(code: str) -> SKU:  # pragma: no cover
    """Return SKU or raise KeyError. Provider: Logistics."""
    raise NotImplementedError


def validate_sku(code: str) -> None:  # pragma: no cover
    """Raise ValueError if code is not valid by schema/pattern."""
    raise NotImplementedError


def list_substitutions(code: str) -> list[Substitution]:  # pragma: no cover
    raise NotImplementedError


def cost_for(
    code: str, as_of_iso: str | None = None
) -> int:  # pragma: no cover
    """Return effective cost in cents at as_of_iso (UTC ISO-8601)."""
    raise NotImplementedError
