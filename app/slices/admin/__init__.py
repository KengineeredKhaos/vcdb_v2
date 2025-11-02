# app/slices/admin/__init__.py
from flask import Blueprint

bp = Blueprint(
    "admin", __name__, url_prefix="/admin", template_folder="templates"
)
from . import models  # noqa
