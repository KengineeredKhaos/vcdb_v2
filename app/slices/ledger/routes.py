# app/slices/ledger/routes.py
from __future__ import annotations

from flask import Blueprint, jsonify, request

from .services import verify_chain

bp = Blueprint(
    "ledger", __name__, url_prefix="/ledger", template_folder="templates"
)


@bp.get("/verify")
def verify_endpoint():
    chain_key = request.args.get("chain_key") or None
    return jsonify(verify_chain(chain_key))
