#!/usr/bin/env python3
# vcdb-v2/tools/fix_drop_type_kwarg.py
import re, sys, pathlib

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "migrations",
    "__pycache__",
    "tests_legacy",
}


def should_skip(p: pathlib.Path) -> bool:
    return any(part in SKIP_DIRS for part in p.parts)


emit_re = re.compile(r"event_bus\.emit\s*\(", re.M)


def find_call_span(s, start_idx):
    depth = 0
    i = start_idx
    while i < len(s) and s[i] != "(":
        i += 1
    if i >= len(s):
        return None
    depth, a0 = 1, i + 1
    while i < len(s):
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return (a0, i)
        i += 1
    return None


def has_kw(args_src, name):
    return re.search(rf"\b{name}\s*=", args_src) is not None


def drop_type_kw(args_src):
    # remove patterns like: , type=...,  type=...,  ,type=...
    # (naively balanced until next comma or closing paren)
    return re.sub(r"(,\s*)?type\s*=\s*[^,)\n]+", "", args_src)


def process_file(p: pathlib.Path):
    src = p.read_text(encoding="utf-8")
    out = []
    i = 0
    changed = False
    while True:
        m = emit_re.search(src, i)
        if not m:
            out.append(src[i:])
            break
        out.append(src[i : m.end()])
        span = find_call_span(src, m.end() - 1)
        if not span:
            out.append(src[m.end() :])
            break
        a0, a1 = span
        args_src = src[a0:a1]

        # only drop type= if both domain and operation are present
        if (
            has_kw(args_src, "domain")
            and has_kw(args_src, "operation")
            and has_kw(args_src, "type")
        ):
            new_args = drop_type_kw(args_src)
            # clean up accidental trailing commas like "(a=1, , b=2)"
            new_args = re.sub(r",\s*,", ", ", new_args)
            # and stray leading/trailing commas
            new_args = re.sub(r"^\s*,\s*", "", new_args)
            new_args = re.sub(r"\s*,\s*$", "", new_args)
            out.append(new_args)
            changed = changed or (new_args != args_src)
        else:
            out.append(args_src)

        i = a1
    if changed:
        p.write_text("".join(out), encoding="utf-8")
        print(f"fixed: {p}")
    return changed


def main(roots):
    any_change = False
    for root in roots or ["."]:
        for p in pathlib.Path(root).rglob("*.py"):
            if should_skip(p):
                continue
            try:
                if process_file(p):
                    any_change = True
            except Exception as e:
                print(f"skip {p}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
