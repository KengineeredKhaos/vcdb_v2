# app/slices/ledger/routes.py
from __future__ import annotations
from flask import jsonify, request
from . import bp
from .services import verify_chain


@bp.get("/verify")
def verify_endpoint():
    chain_key = request.args.get("chain_key") or None
    return jsonify(verify_chain(chain_key))
