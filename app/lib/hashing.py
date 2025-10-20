# app/lib/hashing.py
# -*- coding: utf-8 -*-
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Stable library primitive for VCDB.
# Canon API: lib-core v1.0.0 (frozen)

import hashlib

from .jsonutil import stable_dumps


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(obj) -> str:
    return sha256_hex(stable_dumps(obj).encode("utf-8"))
