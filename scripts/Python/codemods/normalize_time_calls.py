#!/usr/bin/env python3
"""
Normalize time calls in repo code (NOT venv):
- datetime.utcnow()           -> _now()
- datetime.now()  (no args)   -> _now()
Adds: from app.lib.time import _now  (if missing)

Run (dry):   PYTHONPATH=. python scripts/Python/codemods/normalize_time_calls.py
Run (write): PYTHONPATH=. python scripts/Python/codemods/normalize_time_calls.py --apply
"""
from __future__ import annotations

import argparse
import pathlib

import libcst as cst
from libcst.metadata import MetadataWrapper, QualifiedNameProvider

ROOTS = ["app", "scripts", "tests"]
IMPORT_STMT = "from app.lib.time import _now\n"


class TimeRefactor(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (QualifiedNameProvider,)

    def __init__(self) -> None:
        self.need_now_import = False
        self._module_src: str | None = None  # we’ll set this in process()

    # wire original source so we can check for existing import via substring
    def set_source(self, src: str) -> None:
        self._module_src = src

    def leave_Call(
        self, node: cst.Call, updated: cst.Call
    ) -> cst.BaseExpression:
        # Examine the qualified name of the callable (if LibCST can resolve it)
        try:
            qnames = self.get_metadata(
                QualifiedNameProvider, node.func, default=set()
            )
        except Exception:
            qnames = set()
        name = next(iter(qnames), None)
        qn = name.name if name else ""

        # Replace datetime.utcnow()
        if qn.endswith(".datetime.utcnow"):
            self.need_now_import = True
            return cst.parse_expression("_now()")

        # Replace datetime.now() *only when there are no args/keywords*
        if qn.endswith(".datetime.now"):
            has_args = bool(updated.args)
            if not has_args:
                self.need_now_import = True
                return cst.parse_expression("_now()")

        return updated

    def leave_Module(
        self, node: cst.Module, updated: cst.Module
    ) -> cst.Module:
        if not self.need_now_import:
            return updated
        src = self._module_src or updated.code
        if IMPORT_STMT.strip() in src:
            return updated  # import already present

        # Insert import at top (after __future__ if any)
        body = list(updated.body)
        insert_at = 0
        # keep __future__ imports at very top
        while (
            insert_at < len(body)
            and isinstance(body[insert_at], cst.SimpleStatementLine)
            and isinstance(body[insert_at].body[0], cst.ImportFrom)
            and getattr(body[insert_at].body[0].module, "value", "")
            == "__future__"
        ):
            insert_at += 1

        new_import = cst.parse_statement(IMPORT_STMT)
        body.insert(insert_at, new_import)
        return updated.with_changes(body=body)


def process(path: pathlib.Path, apply: bool) -> bool:
    src = path.read_text(encoding="utf-8")
    try:
        module = cst.parse_module(src)
    except Exception as e:
        print(f"SKIP (parse error): {path}  -> {e}")
        return False

    wrapper = MetadataWrapper(module)
    xf = TimeRefactor()
    xf.set_source(src)
    try:
        new_module = wrapper.visit(xf)
    except Exception as e:
        print(f"SKIP (transform error): {path}  -> {e}")
        return False

    if new_module.code != src:
        if apply:
            path.write_text(new_module.code, encoding="utf-8")
        else:
            print(f"Would change {path}")
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    changed = 0
    for root in ROOTS:
        for p in pathlib.Path(root).rglob("*.py"):
            # extra safety: skip hidden dirs and venv-like paths
            sp = str(p)
            if any(seg.startswith(".") for seg in p.parts):
                continue
            if (
                "/lib/python" in sp
                or "/site-packages/" in sp
                or "/venv/" in sp
                or "/.venv/" in sp
            ):
                continue
            if process(p, args.apply):
                changed += 1

    print(("Changed" if args.apply else "Would change"), changed, "files")


if __name__ == "__main__":
    main()
