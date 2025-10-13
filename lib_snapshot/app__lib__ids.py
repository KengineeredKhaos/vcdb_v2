# app/lib/ids.py
from ulid import ULID


def new_ulid() -> str:
    return str(ULID())  # 26-char, k-sortable
