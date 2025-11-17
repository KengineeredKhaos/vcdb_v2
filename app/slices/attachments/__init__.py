# app/slices/attachments/__init__.py
from __future__ import annotations

from flask import Blueprint

bp = Blueprint("attachments", __name__, url_prefix="/attachments")

from . import models  # noqa: E402,F401
