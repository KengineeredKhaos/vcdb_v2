from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# --- Paths ---
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
SLICES_DIR = APP / "slices"
LIB_DIR = APP / "lib"

# Slices you may want to exempt temporarily (devtools is intentionally disposable)
EXEMPT_SLICES_FROM_MAPPER = {"devtools"}


@dataclass(frozen=True)
class Violation:
    path: Path
    lineno: int
    message: str

    def format(self) -> str:
        loc = f"{self.path}:{self.lineno}" if self.lineno else str(self.path)
        return f"- {loc}: {self.message}"


def _py_files(base: Path) -> list[Path]:
    return [p for p in base.rglob("*.py") if p.is_file()]


def _slice_name_for(path: Path) -> str | None:
    # app/slices/<slice>/...
    try:
        rel = path.relative_to(SLICES_DIR)
    except ValueError:
        return None
    return rel.parts[0] if rel.parts else None


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return None


def _iter_imports(tree: ast.AST) -> Iterable[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.lineno, node.module


def _dotted(expr: ast.AST) -> str:
    # Best-effort dotted name for commit/rollback base expressions
    try:
        return ast.unparse(expr)  # py3.9+
    except Exception:
        return ""


def _iter_attr_calls(tree: ast.AST) -> Iterable[tuple[int, str, str]]:
    # yields: (lineno, base_expr_dotted, attr)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(
            node.func, ast.Attribute
        ):
            base = _dotted(node.func.value)
            yield node.lineno, base, node.func.attr


def _is_service_file(path: Path) -> bool:
    # Your repo has:
    # - app/slices/<slice>/services.py
    # - app/slices/finance/services_*.py
    # - app/slices/logistics/issuance_services.py
    # Treat anything inside a slice that looks "service-y" as service code.
    if _slice_name_for(path) is None:
        return False
    name = path.name
    if name == "services.py":
        return True
    if name.startswith("services_") and name.endswith(".py"):
        return True
    if name.endswith("_services.py"):
        return True
    return False


def check_no_cross_slice_imports() -> list[Violation]:
    """
    In app/slices/<slice>/..., forbid absolute imports of app.slices.<other_slice>.*
    """
    violations: list[Violation] = []
    for f in _py_files(SLICES_DIR):
        tree = _parse(f)
        if tree is None:
            continue

        slice_name = _slice_name_for(f)
        if not slice_name:
            continue

        for lineno, mod in _iter_imports(tree):
            if not mod.startswith("app.slices."):
                continue
            parts = mod.split(".")
            if len(parts) >= 3:
                imported_slice = parts[2]
                if imported_slice != slice_name:
                    violations.append(
                        Violation(
                            f,
                            lineno,
                            f"Cross-slice import '{mod}' (slice '{slice_name}' importing '{imported_slice}'). "
                            "Use extensions/contracts instead.",
                        )
                    )
    return violations


def check_lib_does_not_import_slices() -> list[Violation]:
    violations: list[Violation] = []
    for f in _py_files(LIB_DIR):
        tree = _parse(f)
        if tree is None:
            continue
        for lineno, mod in _iter_imports(tree):
            if mod.startswith("app.slices."):
                violations.append(
                    Violation(
                        f,
                        lineno,
                        f"lib-core imports slice code '{mod}'. app/lib must not depend on slices.",
                    )
                )
    return violations


def check_services_flush_only() -> list[Violation]:
    """
    Forbid db.session.commit/rollback (and session.commit/rollback) inside slice services.
    """
    violations: list[Violation] = []
    for f in _py_files(SLICES_DIR):
        if not _is_service_file(f):
            continue

        tree = _parse(f)
        if tree is None:
            continue

        for lineno, base, attr in _iter_attr_calls(tree):
            if attr not in {"commit", "rollback"}:
                continue
            base_norm = base.replace(" ", "")
            if base_norm in {"db.session", "session"}:
                violations.append(
                    Violation(
                        f,
                        lineno,
                        f"Forbidden call '{base}.{attr}()' inside services (services are flush-only).",
                    )
                )
    return violations


def check_each_slice_has_mapper(strict: bool) -> list[Violation]:
    violations: list[Violation] = []
    for slice_dir in sorted([p for p in SLICES_DIR.iterdir() if p.is_dir()]):
        name = slice_dir.name
        if name in EXEMPT_SLICES_FROM_MAPPER:
            continue

        mapper = slice_dir / "mapper.py"
        if not mapper.exists():
            msg = (
                f"Missing mapper.py for slice '{name}' "
                f"(required at app/slices/{name}/mapper.py)."
            )
            # In non-strict mode, we report as a violation but do not fail the run.
            violations.append(
                Violation(mapper, 0, msg + (" (WARN)" if not strict else ""))
            )
    return violations


def main(argv: list[str]) -> int:
    strict = "--strict" in argv

    violations: list[Violation] = []
    violations.extend(check_no_cross_slice_imports())
    violations.extend(check_lib_does_not_import_slices())
    violations.extend(check_services_flush_only())
    mapper_violations = check_each_slice_has_mapper(strict=strict)

    if mapper_violations:
        if strict:
            violations.extend(mapper_violations)
        else:
            print(
                "guardrails: mapper.py warnings (run with --strict to enforce):"
            )
            for v in mapper_violations:
                print(v.format())
            print()

    if not violations:
        print("guardrails: OK")
        return 0

    print("guardrails: FAIL\n")
    for v in violations:
        print(v.format())
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
