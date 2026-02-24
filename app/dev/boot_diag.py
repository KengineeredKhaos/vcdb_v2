# app/dev/boot_diag.py
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from flask import Flask
from sqlalchemy import inspect, text

from app.lib.jsonutil import json


def run_on_boot(app: Flask) -> None:
    """
    Dev-only diagnostics. Centralized boot checks.

    Controlled by config:
      DEV_BOOT_DIAG = True/False
      DEV_DUMP_ROUTES = True/False
      DEV_DUMP_ROUTES_ALL_METHODS = True/False
      DEV_BOOT_SANITY = True/False
      DEV_SCHEMA_CHECK = True/False
      DEV_SCHEMA_CHECK_DEEP = False/True
      DEV_CONFIG_FINGERPRINT = True/False
      DEV_POLICY_FINGERPRINT = True/False
      DEV_POLICY_FINGERPRINT_LIST = True/False
      DEV_LEDGER_CHECK = False/True
      DEV_LEDGER_CHECK_LIMIT = int
    """
    if not app.debug:
        return
    if not bool(app.config.get("DEV_BOOT_DIAG", True)):
        return

    if bool(app.config.get("DEV_DUMP_ROUTES", True)):
        dump_routes(app)

    if bool(app.config.get("DEV_BOOT_SANITY", True)):
        boot_sanity(app)

    if bool(app.config.get("DEV_SCHEMA_CHECK", True)):
        schema_check(app)

    if bool(app.config.get("DEV_LEDGER_CHECK", False)):
        limit = int(app.config.get("DEV_LEDGER_CHECK_LIMIT", 20))
        ledger_sanity(app, limit=limit)


def boot_sanity(app: Flask) -> None:
    from app.extensions import login_manager

    print("\n=== BOOT SANITY ===")
    print(f"ENV                : {app.config.get('ENV', 'unknown')}")
    print(f"DATABASE           : {app.config.get('DATABASE')}")
    print(f"INSTANCE_PATH      : {app.instance_path}")
    sk = app.config.get("SECRET_KEY")
    sk_state = f"OK (len={len(sk)})" if sk else "NO"
    print(f"SECRET_KEY set?    : {sk_state}")
    print(f"Jinja Undefined    : {type(app.jinja_env.undefined).__name__}")

    bp_names = sorted(app.blueprints.keys())
    print(f"Blueprints         : {', '.join(bp_names)}")

    # Counts (useful “is the wiring right?” signal)
    route_count = len(list(app.url_map.iter_rules()))
    view_fn_count = len(app.view_functions)
    bp_count = len(app.blueprints)
    print("=== Counts ===")
    print(f"blueprints         : {bp_count}")
    print(f"routes             : {route_count}")
    print(f"endpoints/views    : {view_fn_count}")

    # Flask extensions bound
    ext_keys = sorted(app.extensions.keys())
    print("Extensions loaded  :", ", ".join(ext_keys))

    # Flask-Login sanity
    lm_ext = app.extensions.get("login_manager")
    lm_bound = lm_ext is not None
    user_loader_set = (
        getattr(login_manager, "_user_callback", None) is not None
    )
    req_loader_set = (
        getattr(login_manager, "_request_callback", None) is not None
    )
    login_view = getattr(login_manager, "login_view", None) or "—"

    print("=== Flask-Login ===")
    print(f"login_manager ext  : {'OK' if lm_bound else 'NO'}")
    print(f"user_loader set    : {'OK' if user_loader_set else 'NO'}")
    print(f"request_loader set : {'OK' if req_loader_set else 'NO'}")
    print(f"login_view         : {login_view}")

    if bool(app.config.get("DEV_CONFIG_FINGERPRINT", True)):
        _print_config_fingerprint(app)

    if bool(app.config.get("DEV_POLICY_FINGERPRINT", True)):
        _print_policy_fingerprint(app)

    print("====================\n")


def _print_config_fingerprint(app: Flask) -> None:
    safe = {
        "ENV": app.config.get("ENV"),
        "DEBUG": bool(app.debug),
        "TESTING": bool(app.testing),
        "DATABASE": app.config.get("DATABASE"),
        "INSTANCE_PATH": app.instance_path,
        "SERVER_NAME": app.config.get("SERVER_NAME"),
        "PREFERRED_URL_SCHEME": app.config.get("PREFERRED_URL_SCHEME"),
        "TEMPLATES_AUTO_RELOAD": app.config.get("TEMPLATES_AUTO_RELOAD"),
        "SESSION_COOKIE_SECURE": app.config.get("SESSION_COOKIE_SECURE"),
        "SESSION_COOKIE_SAMESITE": app.config.get("SESSION_COOKIE_SAMESITE"),
        "WTF_CSRF_ENABLED": app.config.get("WTF_CSRF_ENABLED"),
        "SECRET_KEY_SET": bool(app.config.get("SECRET_KEY")),
        "SECRET_KEY_LEN": (len(app.config.get("SECRET_KEY") or "")),
    }
    raw = json.dumps(
        safe,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    fp = hashlib.sha256(raw).hexdigest()[:12]
    print("======= Config fingerprint =======")
    print(f"fingerprint        : {fp}")
    print("==================================")


def _print_policy_fingerprint(app: Flask) -> None:
    """
    Fingerprint the governance policy tree (catalog + policies + schemas) so
    stale file trees are obvious without file hunting.
    """
    show_list = bool(app.config.get("DEV_POLICY_FINGERPRINT_LIST", True))

    try:
        from app.extensions import policies as pol
    except Exception as exc:
        print("=== Governance policy fingerprint ===")
        print(f"unavailable         : {exc}")
        print("======================================")
        return

    gov_data = getattr(pol, "GOV_DATA", None)
    gov_index = getattr(pol, "GOV_INDEX", None)
    if not gov_data or not gov_index:
        print("=== Governance policy fingerprint ===")
        print("unavailable         : GOV_DATA/GOV_INDEX not found")
        print("=====================================")
        return

    def file_hash(p: Path) -> str:
        try:
            b = p.read_bytes()
        except Exception:
            return "missing"
        return hashlib.sha256(b).hexdigest()[:12]

    try:
        idx = json.loads(Path(gov_index).read_text(encoding="utf-8"))
    except Exception as exc:
        print("=== Governance policy fingerprint ===")
        print(f"index load failed   : {exc}")
        print("=====================================")
        return

    entries = list(idx.get("policies") or [])
    pieces: list[str] = []
    rows: list[dict[str, str]] = []

    for ent in entries:
        pkey = str(ent.get("policy_key") or "")
        pfile = str(ent.get("filename") or "")
        sfile = str(ent.get("schema_filename") or "")

        ppath = Path(gov_data) / pfile if pfile else None
        spath = Path(gov_data) / sfile if sfile else None

        ph = file_hash(ppath) if ppath else "missing"
        sh = file_hash(spath) if spath else "none"

        ver = "?"
        eff = "?"
        if ppath and ppath.exists():
            try:
                pj = json.loads(ppath.read_text(encoding="utf-8"))
                meta = pj.get("meta") or {}
                ver = str(meta.get("version") or "?")
                eff = str(meta.get("effective_on") or "?")
            except Exception:
                ver = "bad_json"
                eff = "bad_json"

        pieces.append(f"{pkey}:{ver}:{eff}:{ph}:{sh}")
        rows.append(
            {
                "policy_key": pkey,
                "version": ver,
                "effective_on": eff,
                "policy_hash": ph,
                "schema_hash": sh,
            }
        )

    raw = "\n".join(sorted(pieces)).encode("utf-8")
    fp = hashlib.sha256(raw).hexdigest()[:12]

    print("=== Governance policy fingerprint ===")
    print(f"catalog entries     : {len(entries)}")
    print(f"fingerprint         : {fp}")

    if show_list and rows:
        for r in sorted(rows, key=lambda x: x["policy_key"]):
            pk = r["policy_key"]
            ver = r["version"]
            eff = r["effective_on"]
            ph = r["policy_hash"]
            sh = r["schema_hash"]
            print(
                f"  - {pk:18} v{ver:>2} eff={eff:10} "
                f"policy={ph} schema={sh}"
            )
    print("=====================================")


def dump_routes(app: Flask) -> None:
    print("\n=== ROUTES ===")
    all_methods = bool(app.config.get("DEV_DUMP_ROUTES_ALL_METHODS", False))
    rows: list[tuple[str, str, str]] = []
    for rule in app.url_map.iter_rules():
        meths = sorted(rule.methods or [])
        if not all_methods:
            allow = {"GET", "POST", "PUT", "PATCH", "DELETE"}
            meths = [m for m in meths if m in allow]
        methods = ",".join(meths)
        rows.append((rule.rule, methods, rule.endpoint))
    for rule, methods, endpoint in sorted(rows, key=lambda x: (x[0], x[1])):
        print(f"{methods:12} {rule:35} -> {endpoint}")
    print("=== END ROUTES ===")
    print("DEV_DB_PATH =", app.config.get("DATABASE"))


def schema_check(app: Flask) -> None:
    from app.extensions import db

    deep = bool(app.config.get("DEV_SCHEMA_CHECK_DEEP", False))
    prefixes = app.config.get("SCHEMA_CHECK_PREFIXES") or []
    ignore_unknown = set(app.config.get("SCHEMA_CHECK_IGNORE_UNKNOWN") or [])

    def norm_db_type(name: str) -> str:
        if not name:
            return ""
        up = str(name).upper().strip()
        if "(" in up:
            up = up.split("(", 1)[0].strip()
        return up

    def type_equiv(model_t: str, db_t: str) -> bool:
        db_tn = norm_db_type(db_t)
        if not db_tn:
            # Dialect didn't report something reliable; don't warn.
            return True

        aliases = {
            "String": {"VARCHAR", "NVARCHAR", "TEXT", "CHAR"},
            "Text": {"TEXT", "CLOB"},
            "Integer": {"INTEGER", "INT"},
            "DateTime": {"DATETIME", "TIMESTAMP"},
            "Date": {"DATE"},
            "Boolean": {"BOOLEAN", "BOOL", "INTEGER"},
        }

        if model_t.upper() == db_tn:
            return True
        return db_tn in aliases.get(model_t, set())

    def type_name(coltype: Any) -> str:
        if coltype is None:
            return ""
        try:
            return coltype.__class__.__name__
        except Exception:
            return str(coltype)

    with app.app_context():
        insp = inspect(db.engine)
        declared = dict(db.metadata.tables)
        existing = set(insp.get_table_names())

        missing = sorted([t for t in declared if t not in existing])
        unknown = sorted((existing - set(declared)) - ignore_unknown)

        app.logger.info("=== SCHEMA CHECK ===")
        app.logger.info(
            "declared:%d existing:%d deep:%s",
            len(declared),
            len(existing),
            deep,
        )
        if missing:
            app.logger.warning("MISSING tables: %s", ", ".join(missing))
        if unknown:
            app.logger.warning("UNKNOWN tables: %s", ", ".join(unknown))

        if not deep:
            return

        def in_scope(tname: str) -> bool:
            if not prefixes:
                return True
            return any(tname.startswith(pfx) for pfx in prefixes)

        for tname, table in declared.items():
            if tname not in existing or not in_scope(tname):
                continue
            db_cols = {c["name"]: c for c in insp.get_columns(tname)}
            model_cols = {c.name: c for c in table.columns}
            issues: list[str] = []

            miss_cols = [c for c in model_cols if c not in db_cols]
            unk_cols = [c for c in db_cols if c not in model_cols]
            if miss_cols:
                issues.append("missing: " + ", ".join(sorted(miss_cols)))
            if unk_cols:
                issues.append("unknown: " + ", ".join(sorted(unk_cols)))

            pk = insp.get_pk_constraint(tname) or {}
            db_pk = set(pk.get("constrained_columns") or [])

            for cname in sorted(set(model_cols) & set(db_cols)):
                mcol = model_cols[cname]
                dcol = db_cols[cname]

                if bool(mcol.nullable) != bool(dcol.get("nullable", True)):
                    issues.append(
                        f"{cname}: nullable model={bool(mcol.nullable)} "
                        f"db={bool(dcol.get('nullable', True))}"
                    )

                if bool(mcol.primary_key) != (cname in db_pk):
                    issues.append(
                        f"{cname}: pk model={bool(mcol.primary_key)} "
                        f"db={(cname in db_pk)}"
                    )

                m_t = type_name(mcol.type)
                d_t = type_name(dcol.get("type"))
                if m_t and not type_equiv(m_t, d_t):
                    issues.append(f"{cname}: type {m_t} vs {d_t}")

            if issues:
                app.logger.warning("[%s] %s", tname, " | ".join(issues))


def ledger_sanity(app: Flask, limit: int = 20) -> None:
    from app.extensions import db

    with app.app_context():
        insp = inspect(db.engine)
        tables = set(insp.get_table_names())
        if "ledger_event" in tables:
            tname = "ledger_event"
        elif "transactions_ledger" in tables:
            tname = "transactions_ledger"
        else:
            print("Ledger sanity skipped (no ledger table present).")
            return

        rows = (
            db.session.execute(
                text(
                    f"""
                    SELECT id, happened_at_utc, prev_event_id, prev_hash,
                           event_hash, type, domain, operation, request_id,
                           actor_ulid, target_id, entity_ids_json,
                           changed_fields_json, refs_json
                      FROM {tname}
                  ORDER BY happened_at_utc DESC, id DESC
                     LIMIT :lim
                    """
                ),
                {"lim": limit},
            )
            .mappings()
            .all()
        )
        if not rows:
            print("LEDGER: empty (no events yet)")
            return

    def stable_hash(payload: dict) -> str:
        canonical = {
            "id": payload.get("id"),
            "happened_at_utc": payload.get("happened_at_utc"),
            "prev_event_id": payload.get("prev_event_id"),
            "prev_hash": payload.get("prev_hash"),
            "type": payload.get("type"),
            "domain": payload.get("domain"),
            "operation": payload.get("operation"),
            "request_id": payload.get("request_id"),
            "actor_ulid": payload.get("actor_ulid"),
            "target_id": payload.get("target_id"),
            "entity_ids_json": payload.get("entity_ids_json"),
            "changed_fields_json": payload.get("changed_fields_json"),
            "refs_json": payload.get("refs_json"),
        }
        raw = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    mismatches: list[dict] = []
    for i in range(len(rows) - 1):
        cur = dict(rows[i])
        prev = dict(rows[i + 1])

        link_ok = (cur.get("prev_event_id") == prev.get("id")) and (
            cur.get("prev_hash") == prev.get("event_hash")
        )
        hash_ok = stable_hash(cur) == cur.get("event_hash")

        if not (link_ok and hash_ok):
            mismatches.append(
                {
                    "id": cur.get("id"),
                    "link_ok": link_ok,
                    "hash_ok": hash_ok,
                    "prev_event_id": cur.get("prev_event_id"),
                    "expected_prev_id": prev.get("id"),
                }
            )

    print(
        "LEDGER:",
        f"head={rows[0]['id']} tail(window)={rows[-1]['id']} "
        f"checked={len(rows)}",
    )
    if mismatches:
        print("LEDGER: issues detected:", len(mismatches))
        for m in mismatches[:5]:
            print(
                "  -",
                f"id={m['id']} link_ok={m['link_ok']} "
                f"hash_ok={m['hash_ok']} prev_event_id={m['prev_event_id']} "
                f"expected_prev_id={m['expected_prev_id']}",
            )
    else:
        print("LEDGER: chain OK for last", len(rows), "events")
