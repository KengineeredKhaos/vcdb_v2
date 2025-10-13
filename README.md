# Project Title: vcdb-v2

Code follows VCDBv2 specs. All decisions are pinned in respective slice.

### Configuration & secrets:

Use instance/config.py + .env for paths (DB at /var/lib/vcdb/app.db), timezone, and role seeds.

### Documentation:

/scaffolding_docs/ contains original slice specifications (MVP)
These are strictly baseline MVP files. Each slice will get skinny routes,
fat services, forms & templates local to slice as project evolves.

**venv Basics:** (because old guys forget stuff)

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

**wheelhouse can be reused on the server:**

```bash
pip download -r requirements.txt -d wheelhouse/
```

### Initial Structure:

```bash
Directory layout (matches canonical)
#
vcdb-v2/
├─ manage_vcdb.py
├─ config.py
├─ requirements.txt
├─ app/
│ ├─ __init__.py
│ ├─ extensions/
│ │ └─ __init__.py
│ ├─ lib/
│ │ ├─ __init__.py
│ │ ├─ utils.py
│ │ └─ security.py
│ ├─ services/
│ │ ├─ __init__.py
│ │ └─ docs_library.py
│ ├─ slices/
│ │ ├─ __init__.py parent 'v2' blueprint + renderer
│ │ ├─ customers/
│ │ │ ├─ __init__.py
│ │ │ ├─ routes.py
│ │ │ ├─ forms.py placeholder (slice-owned forms)
│ │ │ └─ templates/
│ │ │ └─ customers/hello.html
│ │ ├─ calendar/
│ │ ├─ governance/
│ │ ├─ inventory/
│ │ │ └─ templates/
│ │ ├─ resources/
│ │ │ └─ templates/
│ │ ├─ sponsors/
│ │ │ └─ templates/
│ │ └─ transactions/
│ ├─ static/
│ │ ├─ css/
│ │ │ └─ v2.css
│ │ └─ documents/
│ ├─ templates/
│ │ └─ layout/
│ │ └─ base.html
│ └─ logs/ # DEV-ONLY JSONL logs (no PII)
│ ├─ app.log # app events & errors (names-only)
│ ├─ audit.log # RBAC/auth/override/admin actions
│ ├─ jobs.log # nightly/cron runs
│ └─ export.log # public export runs + checksums
└─ alembic/ (created after `flask db init`)
```

### Dev database bootstrap:

Use scripts/init_db.py to apply the schema 
exactly as in ERD & Table Constraints (MVP).
Seeds roles, authorizations (spend cap), 
holidays/blackouts, tier thresholds, minimal enums.

### Dev jobs & logs (skeleton only)

Test cron entries for: 02:05 tier roll-up, 02:15 backup, 
weekly/monthly jobs (paths in .env). Make sure logs land 
in logs/cron.log and your app log includes a tiering.ok marker.

Do not commit secrets or CA keys.
keep .env in gitignore
