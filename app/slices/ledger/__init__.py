# app/slices/ledger/__init__.py

from __future__ import annotations

"""
Ledger package initializer.

Deliberately service-safe:
- do not import routes here
- do not import admin_issue_routes here
- do not import services here

Contracts may import app.slices.ledger.services during app startup.
If this package initializer imports Flask route modules, the Ledger
write path can circular-import through event_bus -> ledger_v2 -> services.
"""

__all__: list[str] = []
