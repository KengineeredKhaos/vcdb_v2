# app/slices/calendar/__init__.py

from __future__ import annotations

from .routes import bp

__all__ = ["bp"]

"""
Calendar’s internal pipeline:

Project plan
project header + task set + planning assumptions

Budget development
roll up the task plan into an internal budget picture

Funding strategy
capture how this project expects to be supported

Demand draft
derive an ask from project scope + budget + funding strategy

Governance review stage
attach/approve semantics for publishability

Execution tracking
encumber / spend / support realization / closeout against that basis
"""
