# heredoc python route securtiy gating search

python - <<'PY'
from pathlib import Path
import re

ROOT = Path("app/slices")

route_pat = re.compile(r'^\s*@\w+\.(?:route|get|post|put|patch|delete)\b')
vcdb_pat = re.compile(r'^\s*#\s*VCDB-SEC: OPEN')

for path in sorted(ROOT.rglob("*.py")):
    lines = path.read_text(encoding="utf-8").splitlines()

    i = 0
    while i < len(lines):
        if route_pat.match(lines[i]):
            start = i

            # Walk upward over stacked decorators and blank lines
            j = start - 1
            while j >= 0 and (
                lines[j].strip() == "" or lines[j].lstrip().startswith("@")
            ):
                j -= 1

            # A route is considered classified only if the first
            # nonblank, non-decorator line above it is # VCDB-SEC:
            classified = j >= 0 and vcdb_pat.match(lines[j])

            if not classified:
                print(f"{path}:{start+1}: {lines[start].strip()}")

            # Skip stacked decorators as one block
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith("@"):
                i += 1
            continue

        i += 1
PY
