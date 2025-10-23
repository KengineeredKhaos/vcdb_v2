#!/usr/bin/env python3
# vcdb-v2/tools/audit_emit_calls.py
import ast, sys, pathlib, json

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
REQUIRED = {"domain", "operation", "request_id", "chain_key"}
LEGACY = {
    "actor_id",
    "target_id",
    "happened_at",
    "slice",
    "type",
}  # type is legacy kwarg in your canon


def should_skip(p: pathlib.Path) -> bool:
    return any(part in SKIP_DIRS for part in p.parts)


def audit_file(path: pathlib.Path):
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as e:
        return []

    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []

    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # event_bus.emit(...)
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "emit"):
            continue
        if not (
            isinstance(f.value, ast.Name)
            and f.value.id in {"event_bus", "bus", "events", "evt_bus"}
        ):
            # allow minor variations; tighten if desired
            continue

        # collect kwargs
        kw = {}
        for k in node.keywords:
            if k.arg is not None:
                kw[k.arg] = k.value

        issues = []

        # legacy kwargs present?
        legacy_found = sorted(set(LEGACY).intersection(kw.keys()))
        if legacy_found:
            issues.append({"legacy_kwargs": legacy_found})

        # required keys missing?
        missing = sorted(REQUIRED - set(kw.keys()))
        if missing:
            issues.append({"missing_required": missing})

        # has type= ? flag
        if "type" in kw:
            # if domain/operation exist, we will recommend dropping type
            has_d_o = "domain" in kw and "operation" in kw
            issues.append({"has_type_kwarg": True, "can_drop": has_d_o})

        # warn if neither domain/operation nor type present (broken)
        if not {"domain", "operation"} <= set(kw.keys()) and "type" not in kw:
            issues.append({"broken_envelope": "no domain/operation or type"})

        if issues:
            findings.append(
                {
                    "file": str(path),
                    "line": node.lineno,
                    "issues": issues,
                    "preview": ast.get_source_segment(src, node)
                    or "<unavailable>",
                }
            )
    return findings


def main(roots):
    all_findings = []
    for root in roots or ["."]:
        for p in pathlib.Path(root).rglob("*.py"):
            if should_skip(p):
                continue
            fs = audit_file(p)
            if fs:
                all_findings.extend(fs)

    # pretty print grouped by file
    if not all_findings:
        print("OK: no issues found.")
        return 0

    by_file = {}
    for f in all_findings:
        by_file.setdefault(f["file"], []).append(f)

    for file, items in by_file.items():
        print(f"\n{file}")
        for it in items:
            print(f"  L{it['line']}: {it['issues']}")
            prev = (it["preview"] or "").strip().replace("\n", " ")
            if len(prev) > 180:
                prev = prev[:177] + "..."
            print(f"      {prev}")

    # Also dump a machine-readable summary if you want to grep/CI it:
    # print(json.dumps(all_findings, indent=2))
    return 1  # non-zero so CI can fail on audit warnings if you want


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
