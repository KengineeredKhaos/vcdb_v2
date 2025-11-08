# tests/test_contracts_get_readonly.py
import contextlib
from sqlalchemy import text

READONLY_GETS = [
    ("customers_v2", "get_profile",   {"customer_ulid": "01TESTREADONLY00000000000000"}),
    ("resources_v2", "get_profile",   {"resource_ulid":  "01TESTREADONLY00000000000000"}),
    ("sponsors_v2",  "get_policy",    {"sponsor_ulid":   "01TESTREADONLY00000000000000"}),
    ("governance_v2","get_spending_limits", {}),
    ("governance_v2","get_constraints",     {}),
    ("calendar_v2",  "blackout_ok",   {"when_iso": None}),
    ("logistics_v2", "get_sku_cadence", {"customer_ulid": "01TESTREADONLY00000000000000","sku":"WKH-00"}),
]

def test_contract_gets_do_not_write(app):
    from app.extensions import db
    conn = db.engine.connect()
    try:
        with contextlib.ExitStack() as stack:
            # open a transaction scope first (so PRAGMA doesn't autobegin one for us)
            tx = stack.enter_context(conn.begin())
            # sqlite: turn on query-only mode to forbid writes for this connection
            conn.exec_driver_sql("PRAGMA query_only = ON;")

            for mod_name, fn_name, kwargs in READONLY_GETS:
                mod = __import__(f"app.extensions.contracts.{mod_name}", fromlist=[fn_name])
                fn  = getattr(mod, fn_name)
                # Execute the GET via a connection that forbids writes
                # swap the session bind for the call lifetime
                old = db.session.get_bind()
                db.session.bind = conn
                try:
                    fn(**kwargs)
                finally:
                    db.session.bind = old

            tx.rollback()
    finally:
        conn.close()
