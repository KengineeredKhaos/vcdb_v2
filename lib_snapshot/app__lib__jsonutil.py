# app/lib/jsonutil.py
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, TextIO, Union

Pathish = Union[str, Path]


# ---------- dumps / loads ----------


def stable_dumps(obj: Any) -> str:
    """
    Compact, deterministic JSON string for hashing/ledger storage.
    - sort_keys=True for canonical ordering
    - separators to remove spaces
    """
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def pretty_dumps(obj: Any, *, indent: int = 2) -> str:
    """Human-friendly JSON (stable key order, indented)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=indent)


def try_loads(s: str) -> Any:
    """
    Original helper, left intact: raises if invalid JSON.
    Use safe_loads() if you want a default instead of exceptions.
    """
    return json.loads(s)


def safe_loads(s: str, *, default: Any = None) -> Any:
    """
    Parse JSON defensively. Returns `default` on failure.
    Useful in routes/adapters where you don't want to bomb out.
    """
    try:
        return json.loads(s)
    except Exception:
        return default


# ---------- normalization / equality / hashing ----------


def _normalize(value: Any) -> Any:
    """
    Recursively normalize structures for deterministic comparison:
    - dict keys sorted
    - lists normalized element-wise
    - tuples normalized as lists
    """
    if isinstance(value, dict):
        return {k: _normalize(value[k]) for k in sorted(value.keys())}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, tuple):
        return [_normalize(v) for v in value]
    return value


def is_json_equal(a: Any, b: Any) -> bool:
    """Semantic equality ignoring key order and tuple/list differences."""
    return _normalize(a) == _normalize(b)


def canonical_hash(obj: Any) -> str:
    """
    SHA-256 hash of stable JSON representation. Handy for ledger
    event hashing or content-addressability.
    """
    data = stable_dumps(obj).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# ---------- NDJSON (JSON Lines) ----------


def iter_ndjson(stream: TextIO) -> Iterator[Any]:
    """
    Yield parsed objects from a newline-delimited JSON (NDJSON) stream.
    Skips blank lines; raises on invalid JSON lines.
    """
    for line in stream:
        line = line.strip()
        if not line:
            continue
        yield json.loads(line)


def to_ndjson_lines(items: Iterable[Any]) -> str:
    """
    Return a single string with one compact JSON object per line.
    Use when writing logs/exports that prefer JSONL/NDJSON.
    """
    return "".join(stable_dumps(it) + "\n" for it in items)


# ---------- JSON Merge Patch (RFC 7386-ish) ----------


def json_merge_patch(target: Any, patch: Any) -> Any:
    """
    Apply a minimal JSON Merge Patch to `target` and return a new object.
    - If patch is not a dict, it replaces target entirely.
    - If a key value is `None`, that key is removed from the result (when target is a dict).
    - Otherwise merge recursively.
    """
    if not isinstance(patch, dict) or not isinstance(target, dict):
        # Non-object replaces the target
        return _normalize(patch)

    result = dict(target)
    for k, v in patch.items():
        if v is None:
            result.pop(k, None)
        else:
            if (
                k in result
                and isinstance(result[k], dict)
                and isinstance(v, dict)
            ):
                result[k] = json_merge_patch(result[k], v)
            else:
                result[k] = _normalize(v)
    return result


# ---------- tiny file I/O helpers ----------


def read_json_file(path: Pathish, *, default: Any = None) -> Any:
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_file(
    path: Pathish, data: Any, *, pretty: bool = False
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    txt = pretty_dumps(data) if pretty else stable_dumps(data)
    p.write_text(txt, encoding="utf-8")
