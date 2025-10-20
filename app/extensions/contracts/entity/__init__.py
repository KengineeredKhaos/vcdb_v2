# app/extensions/contracts/entity/__init__.py
# -*- coding: utf-8 -*-
# Re-export entity contracts to the canonical import path
# so: from app.extensions.contracts.entity import v2

from app.extensions.contracts.entity import v2 as v2  # re-export module

__all__ = ["v2"]
