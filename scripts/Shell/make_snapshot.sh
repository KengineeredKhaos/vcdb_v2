#!/usr/bin/env bash
set -euo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
NAME="vcdb-v2-${STAMP}"
OUTDIR="snapshots"
mkdir -p "$OUTDIR"

# 1) Record environment + versions
python -V > .snapshot_env.txt
pip freeze >> .snapshot_env.txt 2>/dev/null || true
git rev-parse --short HEAD >> .snapshot_env.txt 2>/dev/null || echo "no-git" >> .snapshot_env.txt

# 2) Sanity: dump routes + ledger verify (optional but nice to keep)
python - <<'PY'
from app import create_app
from werkzeug.routing import MapAdapter
app = create_app("config.DevConfig")
with app.app_context():
    print("=== ROUTES ===")
    for r in sorted(app.url_map.iter_rules(), key=lambda x: (x.rule,x.methods)):
        methods = ",".join(sorted(m for m in r.methods if m in {"GET","POST","PUT","PATCH","DELETE"}))
        print(f"{methods:16} {r.rule:40} -> {r.endpoint}")
    print("=== END ROUTES ===")
PY

# 3) (Optional) verify ledger chain if you added hashing
if [ -f scripts/verify_ledger_chain.py ]; then
  PYTHONPATH=. python scripts/verify_ledger_chain.py || true
fi

# 4) Build the archive (code + templates + scripts + config + DB + snapshots)
zip -r "${OUTDIR}/${NAME}.zip" \
  app/ \
  scripts/ \
  templates/ \
  var/app-instance/dev.db \
  .snapshot_env.txt \
  -x "app/__pycache__/*" \
     "app/**/__pycache__/*" \
     "scripts/__pycache__/*" \
     "**/*.pyc"

# 5) Checksums
( cd "$OUTDIR" && sha256sum "${NAME}.zip" > "${NAME}.zip.sha256" )

echo "Snapshot: ${OUTDIR}/${NAME}.zip"
echo "SHA256:   $(cat ${OUTDIR}/${NAME}.zip.sha256)"
