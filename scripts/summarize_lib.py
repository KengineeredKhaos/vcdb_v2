# scripts/summarize_lib.py
import ast, hashlib, json, os, re, sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "app" / "lib"
OUT_MD = ROOT / "lib_review_report.md"
SNAP_DIR = ROOT / "lib_snapshot"


def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def read(p: Path) -> bytes:
    return p.read_bytes()


def parse_symbols(py_path: Path) -> Dict[str, object]:
    src = py_path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src, filename=str(py_path))
    except SyntaxError as e:
        return {"error": f"SyntaxError: {e}"}

    toplevel_funcs, toplevel_classes = [], []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            toplevel_funcs.append(node.name)
        elif isinstance(node, ast.ClassDef):
            toplevel_classes.append(node.name)

    # Try to capture __all__ if it’s a simple list/tuple of strings
    public: List[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__all__":
                    try:
                        val = ast.literal_eval(node.value)
                        if isinstance(val, (list, tuple)):
                            public = [x for x in val if isinstance(x, str)]
                    except Exception:
                        pass

    return {
        "functions": sorted(toplevel_funcs),
        "classes": sorted(toplevel_classes),
        "__all__": sorted(public),
    }


def main():
    if not LIB.exists():
        print(f"Not found: {LIB}", file=sys.stderr)
        sys.exit(1)

    SNAP_DIR.mkdir(exist_ok=True)

    files = sorted(
        [p for p in LIB.rglob("*.py") if "__pycache__" not in p.parts]
    )
    index = []
    by_hash: Dict[str, List[str]] = {}
    public_index: Dict[str, List[str]] = {}  # symbol -> [module,...]

    for f in files:
        b = read(f)
        h = sha256_bytes(b)
        rel = f.relative_to(ROOT).as_posix()
        info = {
            "path": rel,
            "size": len(b),
            "sha256": h,
        }

        # snapshot copy (normalized path underscores to keep flat)
        flat = rel.replace("/", "__")
        (SNAP_DIR / flat).write_bytes(b)

        meta = parse_symbols(f)
        info.update(meta)
        index.append(info)

        # track duplicates by file content
        by_hash.setdefault(h, []).append(rel)

        # track public names
        public = meta.get("__all__", []) or []
        # If __all__ absent, you can opt-in to treat top-level defs as public—comment in if desired:
        # if not public:
        #     public = list(set(meta.get("functions", [])) | set(meta.get("classes", [])))

        for name in public:
            public_index.setdefault(name, []).append(rel)

    # Build collisions report
    collisions = {
        sym: mods for sym, mods in public_index.items() if len(mods) > 1
    }
    dup_files = {h: paths for h, paths in by_hash.items() if len(paths) > 1}

    # Write Markdown report
    OUT_MD.write_text(
        "\n".join(
            [
                "# app/lib QC Report",
                "",
                "## Summary",
                f"- Files scanned: **{len(files)}**",
                f"- Public symbols: **{sum(len(i.get('__all__', []) or []) for i in index)}**",
                f"- Duplicate files (by content hash): **{len(dup_files)} groups**",
                f"- Public symbol collisions: **{len(collisions)}**",
                "",
                "## Files",
                "",
                *[
                    f"- `{i['path']}`  — {i['size']} bytes — sha256:{i['sha256'][:12]}  "
                    + (
                        f"\n  - __all__: {', '.join(i['__all__'])}"
                        if i.get("__all__")
                        else ""
                    )
                    + (
                        f"\n  - classes: {', '.join(i['classes'])}"
                        if i.get("classes")
                        else ""
                    )
                    + (
                        f"\n  - functions: {', '.join(i['functions'])}"
                        if i.get("functions")
                        else ""
                    )
                    + (f"\n  - ERROR: {i['error']}" if i.get("error") else "")
                    for i in index
                ],
                "",
                "## Duplicate files (same sha256)",
                *(
                    [
                        "\n".join(
                            [f"- {h[:12]}", *[f"  - {p}" for p in ps], ""]
                        )
                        for h, ps in dup_files.items()
                    ]
                    or ["- none"]
                ),
                "",
                "## Public symbol collisions (__all__)",
                *(
                    [
                        "\n".join(
                            [f"- `{sym}`", *[f"  - {m}" for m in mods], ""]
                        )
                        for sym, mods in sorted(collisions.items())
                    ]
                    or ["- none"]
                ),
                "",
                "## Raw index (JSON)",
                "```json",
                json.dumps(index, indent=2),
                "```",
                "",
                "_Generated by scripts/summarize_lib.py_",
            ]
        ),
        encoding="utf-8",
    )

    print(f"Wrote report: {OUT_MD}")
    print(f"Snapshot copies in: {SNAP_DIR}")


if __name__ == "__main__":
    main()
