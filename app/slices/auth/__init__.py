# app/slices/auth/__init__.py
from __future__ import annotations

from flask import Blueprint, current_app

from app.extensions import login_manager

from .user import load_user

bp = Blueprint(
    "auth", __name__, url_prefix="/auth", template_folder="templates"
)


@login_manager.user_loader
def _load_user(user_id: str):
    # Flask-Login passes a str; your DB query can accept it directly.
    return load_user(user_id)
