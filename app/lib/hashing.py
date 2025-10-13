# app/lib/hashing.py
import hashlib
from .jsonutil import stable_dumps


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(obj) -> str:
    return sha256_hex(stable_dumps(obj).encode("utf-8"))
