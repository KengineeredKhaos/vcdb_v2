# app/extensions/contracts/http.py
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flask import current_app, jsonify

from .errors import ContractError


def respond_ok(payload: Any, status: int = 200):
    return jsonify(payload), status


def respond_error(e: ContractError):
    # Single place to shape API errors + log them
    current_app.logger.error(
        {
            "event": "contract_error",
            **e.to_dict(safe=True),
        }
    )
    return jsonify(e.to_dict(safe=True)), e.http_status


def contract_route(func: Callable[[], Any]) -> tuple[Any, int]:
    """
    Small wrapper for routes that only call contract code.
    Usage:
        return contract_route(lambda: governance_v2.get_role_catalogs())
    """
    try:
        result = func()
        return respond_ok(result)
    except ContractError as e:
        return respond_error(e)
