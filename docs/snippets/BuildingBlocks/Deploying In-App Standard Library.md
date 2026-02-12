# Deploying In-App Standard Library

100%—you’re on the right track. The pattern is:

* put “do-it-everywhere” helpers in `app/lib/*`
* expose a clean **public surface** in `app/lib/__init__.py`
* import from `app.lib` in slices (never from deep files)
* wire any one-time setup (logging, json, time) in `create_app` so every slice gets it for free

Here’s a tight checklist to lock it in.

# 1) Public surface for lib

In `app/lib/__init__.py`, re-export only what you want app-wide:

```python
# app/lib/__init__.py
from .chrono import utc_now, to_iso8601, parse_iso8601, utc_from_timestamp
from .ids import new_ulid, ULID
from .logging import JSONLineFormatter, configure_structured_logging
from .jsonutil import json_loads, json_dumps, try_json_loads
from .schema import DraftValidator, validate_json, ValidationError
from .pagination import paginate, paginate_sa, paginate_list
from .security import password_hash, verify_password, audit_logger

__all__ = [
    "utc_now", "to_iso8601", "parse_iso8601", "utc_from_timestamp",
    "new_ulid", "ULID",
    "JSONLineFormatter", "configure_structured_logging",
    "json_loads", "json_dumps", "try_json_loads",
    "DraftValidator", "validate_json", "ValidationError",
    "paginate", "paginate_sa", "paginate_list",
    "password_hash", "verify_password", "audit_logger",
]
```

Usage everywhere else becomes simple:

```python
from app.lib import utc_now, new_ulid, paginate
```

# 2) App factory wires one-time stuff

Keep global/once-per-app configuration in `create_app`:

```python
# app/__init__.py (excerpt)
from app.lib import configure_structured_logging

def create_app(config_object="config.DevConfig"):
    app = Flask(__name__, template_folder="templates")
    app.config.from_object(config_object)

    # fallbacks…
    app.config.setdefault("DATABASE", app.config.get("DEV_DB_PATH"))
    app.config.setdefault("SECRET_KEY", "dev")
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{app.config['DATABASE']}"

    # logging once, idempotent
    configure_structured_logging(app)

    # any request-scoped IDs, error handlers, etc.
    # register blueprints…

    return app
```

Slices don’t configure logging, JSON, or time—they just use them.

# 3) How slices consume it (DRY)

Example for a service:

```python
# app/slices/governance/services.py
from app.lib import utc_now, json_dumps, validate_json, ValidationError
from .models import Policy

def policy_set(db, key: str, value: dict, schema: dict):
    # validate at boundary
    try:
        validate_json(value, schema)
    except ValidationError as e:
        # raise your slice-local error, or surface via contract
        raise

    row = Policy.get_or_create(db, key)
    row.value_json = json_dumps(value)
    row.updated_at = utc_now()
    db.session.commit()
    return row
```

# 4) Keep contracts thin (facade)

Contracts import from `app.lib` too, but **never** reach into slice internals directly:

```python
# app/extensions/contracts/governance/v1.py
from app.lib import json_dumps
from app.extensions.contracts.errors import ContractDataNotFound, ContractValidationError
from app.slices.governance import services as gov

def get_roles(db):
    result = gov.policy_get(db, "roles")
    if result is None:
        raise ContractDataNotFound("roles not defined")
    return result  # already a dict ready for DTO
```

# 5) Guardrails to avoid drift

* **Never** import from `app/lib/<file>.py` in slices; always from `app.lib`.
* Keep `__all__` limited; if it’s not meant for everyone, don’t export it.
* Prefer **pure functions** in `app/lib` (no app globals), so they’re trivial to test.
* Add small tests for lib helpers—catch regressions early.

# 6) Nice-to-have utilities to centralize (if not already)

* **path safety** / `ensure_dir(path: Path)` helper
* **env casting**: `env_bool`, `env_int`, `env_json`
* **dict tools**: `pick`, `omit`, `deep_merge`
* **crypto**: secure random tokens, HMAC helpers (if you sign payloads)
* **validation**: email/phone/basic URL sanitizers (only if used often)

---

If you keep `app/lib` tidy and treat it as your “shared standard library,” you’ll stop re-implementing the same glue in each slice. The slices stay skinny: they orchestrate, they don’t reinvent utilities.
