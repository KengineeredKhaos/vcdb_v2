# app/slices/entity/__init__.py
from flask import Blueprint

bp = Blueprint(
    "entity", __name__, url_prefix="/entity", template_folder="templates"
)


from . import models, routes  # noqa: E402, F401
