# app/cli.py

"""
VCDB v2 — CLI Primer
====================

How to run these commands
-------------------------
- One-off CLI (no server needed):
    export FLASK_APP=manage_vcdb.py
    flask --help

- Or prefix per-command:
    flask --app manage_vcdb.py <command> [options]

- Start the dev server (separate terminal):
    python manage_vcdb.py run --env dev


Ledger / Audit
--------------
- Verify all chains:
    flask --app manage_vcdb.py ledger-verify

- Verify a specific chain:
    flask --app manage_vcdb.py ledger-verify --chain entity

- Emit N synthetic "smoke" events (quick write-path test):
    flask --app manage_vcdb.py emit-smoke --n 3 --chain smoke


Dev Auth Helpers (debug/stub only)
----------------------------------
- Show the current dev identity and roles:
    flask --app manage_vcdb.py whoami

- Impersonate a role set (comma-separated):
    flask --app manage_vcdb.py impersonate --roles admin,auditor
  (Allowed dev roles come from config: STUB_ROLE_CODES)


Entity (contracts v2)
---------------------
- Ensure a person exists (idempotent):
    flask --app manage_vcdb.py entity-ensure-person --first Jane --last Doe --email jane@example.org
  Dry-run (no writes; shows normalization):
    flask --app manage_vcdb.py entity-ensure-person --first Jane --last Doe --email jane@example.org --dry-run

- Ensure an organization exists (idempotent):
    flask --app manage_vcdb.py entity-ensure-org --legal "Acme Inc" --ein 123456789
  Dry-run:
    flask --app manage_vcdb.py entity-ensure-org --legal "Acme Inc" --ein 123456789 --dry-run

- Attach a (domain/system) role to an entity (idempotent):
    flask --app manage_vcdb.py entity-role-attach --entity 01H...ULID --role governor

- Remove a role:
    flask --app manage_vcdb.py entity-role-remove --entity 01H...ULID --role governor


Handy Shell
-----------
- Open an app-aware Python shell:
    flask --app manage_vcdb.py shell

- In the shell, emit a test event:
    >>> from app.extensions.contracts.ledger import v2 as L
    >>> from app.lib.ids import new_ulid
    >>> L.emit(domain="smoke", operation="ping", request_id=new_ulid(), actor_ulid=None, target_ulid=None)


Notes
-----
- All commands use canon contracts (no ORM leakage).
- Ledger never stores PII; events include ULIDs + field names only.
- Permissions are mapped in config PERMISSIONS_MAP (e.g., 'ledger:read' → admin,auditor).
- For dev/stub auth, change roles via `/auth/dev/impersonate?as=auditor` or the `impersonate` CLI.
"""


from __future__ import annotations
import click

from app.extensions.contracts.ledger import v2 as ledger
from app.lib.ids import new_ulid

# Optional imports used by some commands
from flask import current_app
from flask_login import login_user
from flask import session

# this one breaks the app. Don't remove the comment until Auth slice is canon
# from app.slices.auth.routes import SessionUser  # dev-only helper persona
from app.extensions.contracts.auth import v2 as auth_ro
from app.extensions.contracts.entity import v2 as entity

from app.cli_finance import finance_group

# If you have governance roles policy wired:
# from app.extensions.contracts.governance import v2 as gov


def register_cli(app):
    # ---------------------------------------------------------------------
    # Ledger / Audit
    # ---------------------------------------------------------------------
    @app.cli.command("ledger-verify")
    @click.option(
        "--chain",
        "chain_key",
        default=None,
        help="Verify a specific chain_key; default = all",
    )
    def ledger_verify(chain_key):
        """Verify hash chains in the Ledger."""
        res = ledger.verify(chain_key=chain_key)
        if res.get("ok"):
            chains = ", ".join(res.get("chains", []))
            click.echo(
                f"OK — checked {res.get('checked', 0)} events across chains: {chains}"
            )
        else:
            click.echo(f"BROKEN — {res.get('broken')}")
            raise SystemExit(1)

    @app.cli.command("emit-smoke")
    @click.option(
        "--n", default=1, show_default=True, help="Number of test events"
    )
    @click.option(
        "--chain", default="smoke", show_default=True, help="Domain/chain key"
    )
    def emit_smoke(n, chain):
        """Emit N synthetic events to quickly test the write-path."""
        for i in range(n):
            r = ledger.emit(
                domain=chain,
                operation=f"ping{i}",
                request_id=new_ulid(),
                actor_ulid=None,
                target_ulid=None,
            )
            click.echo(r)

    # Optional: quick dump of latest N events per chain (read-only helper).
    # Implement when you add a ledger read contract. Placeholder:
    # @app.cli.command("ledger-tail")
    # @click.option("--chain", "chain_key", required=False)
    # @click.option("--n", default=10, show_default=True)
    # def ledger_tail(chain_key, n):
    #     """Tail the last N events (requires ledger read contract)."""
    #     ...

    # ---------------------------------------------------------------------
    # Dev Auth / RBAC helpers (STUB mode only)
    # ---------------------------------------------------------------------
    @app.cli.command("whoami")
    def whoami():
        """Print the current dev identity (roles) if stub auth is enabled."""
        if not current_app.debug:
            click.echo("Not in debug mode.")
            return
        ident = session.get("session_user")
        if not ident:
            click.echo(
                "No session_user (visit the app once or use auth/dev/impersonate)."
            )
            return
        roles = ",".join(ident.get("roles", []))
        click.echo(
            f"ULID={ident.get('ulid')} user={ident.get('username')} roles={roles}"
        )

    @app.cli.command("impersonate")
    @click.option(
        "--roles", default="admin", help="CSV of roles (e.g., admin,auditor)"
    )
    def impersonate_cmd(roles):
        """Switch dev persona roles (stub mode)."""
        if not current_app.debug:
            click.echo("Impersonation is only available in debug.")
            return
        allowed = set(
            current_app.config.get(
                "STUB_ROLE_CODES", {"user", "auditor", "admin"}
            )
        )
        roles_list = [
            r
            for r in (x.strip().lower() for x in roles.split(","))
            if r in allowed
        ] or ["user"]
        ident = session.get("session_user") or {
            "ulid": new_ulid(),
            "name": "dev",
            "username": "dev",
            "email": "dev@example.org",
            "roles": roles_list,
        }
        ident["roles"] = roles_list
        session["session_user"] = ident
        login_user(SessionUser(**ident), remember=True)
        click.echo(f"Impersonating roles: {','.join(roles_list)}")

    @app.cli.command("rbac-list")
    def rbac_list():
        """List active RBAC role codes known by Auth (read-only)."""
        codes = auth_ro.list_all_role_codes()
        click.echo(", ".join(codes) if codes else "<none>")

    # ---------------------------------------------------------------------
    # Entity helpers (dev convenience; use contracts v2; dry_run option)
    # ---------------------------------------------------------------------
    @app.cli.command("entity-ensure-person")
    @click.option("--first", required=True, help="First name")
    @click.option("--last", required=True, help="Last name")
    @click.option("--email", default=None)
    @click.option("--phone", default=None)
    @click.option("--dry-run", is_flag=True, default=False)
    def entity_ensure_person(first, last, email, phone, dry_run):
        """Ensure person exists (idempotent). Dry-run shows normalization without writing."""
        env = entity.ContractEnvelope(
            request_id=new_ulid(), actor_id=None, dry_run=dry_run
        )
        res = entity.ensure_person(
            env, first_name=first, last_name=last, email=email, phone=phone
        )
        click.echo(res)

    @app.cli.command("entity-ensure-org")
    @click.option("--legal", "legal_name", required=True, help="Legal name")
    @click.option("--dba", "dba_name", default=None, help="DBA (optional)")
    @click.option("--ein", default=None, help="EIN (9 digits) for dedupe")
    @click.option("--dry-run", is_flag=True, default=False)
    def entity_ensure_org(legal_name, dba_name, ein, dry_run):
        """Ensure organization exists (idempotent)."""
        env = entity.ContractEnvelope(
            request_id=new_ulid(), actor_id=None, dry_run=dry_run
        )
        res = entity.ensure_org(
            env, legal_name=legal_name, dba_name=dba_name, ein=ein
        )
        click.echo(res)

    @app.cli.command("entity-role-attach")
    @click.option("--entity", "entity_ulid", required=True)
    @click.option(
        "--role", "role_code", required=True, help="Domain/system role code"
    )
    def entity_role_attach(entity_ulid, role_code):
        """Attach a role to an entity (idempotent)."""
        env = entity.ContractEnvelope(
            request_id=new_ulid(), actor_id=None, dry_run=False
        )
        res = entity.add_entity_role(env, entity_ulid, role_code)
        click.echo(res)

    @app.cli.command("entity-role-remove")
    @click.option("--entity", "entity_ulid", required=True)
    @click.option("--role", "role_code", required=True)
    def entity_role_remove(entity_ulid, role_code):
        """Remove a role from an entity (idempotent)."""
        env = entity.ContractEnvelope(
            request_id=new_ulid(), actor_id=None, dry_run=False
        )
        res = entity.remove_entity_role(env, entity_ulid, role_code)
        click.echo(res)

    # ---------------------------------------------------------------------
    # Governance seeds (optional, if you want CLI seeding)
    # ---------------------------------------------------------------------
    @app.cli.command("gov-seed-roles")
    def gov_seed_roles():
        """
        Seed baseline domain roles as a Governance policy.
        """
        from app.slices.governance import services as gov_svc

        req = new_ulid()
        value = {"roles": ["customer", "resource", "sponsor", "governor"]}
        row = gov_svc.set_policy(
            "governance",
            "roles",
            value,
            actor_entity_ulid=None,
            request_id=req,
        )
        click.echo(f"Policy governance.roles set to version {row.version}")

    # -------------
    # Finance Group
    # -------------
    app.cli.add_command(finance_group)
