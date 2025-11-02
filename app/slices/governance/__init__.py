# app/slices/governance/__init__.py
from __future__ import annotations

from flask import Blueprint

bp = Blueprint(
    "governance",
    __name__,
    url_prefix="/governance",
    template_folder="templates",
)

from . import models  # noqa: E402,F401

__all__ = ["bp"]
