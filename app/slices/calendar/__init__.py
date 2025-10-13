# Generated scaffolding — VCDB v2 — 2025-09-22 00:11:24 UTC
from __future__ import annotations

from flask import Blueprint

bp = Blueprint(
    "calendar",
    __name__,
    template_folder="templates",
    static_folder=None,
    url_prefix="/calendar",
)

from . import models, routes  # noqa: E402, F401
