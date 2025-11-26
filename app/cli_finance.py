# app/cli_finance.py
from __future__ import annotations

from datetime import datetime, timezone
from inspect import Parameter, signature
from typing import Any, Dict, Optional

import click
from flask.cli import with_appcontext
from sqlalchemy.exc import IntegrityError

from app.cli import echo_db_banner
from app.extensions import db
from app.lib.chrono import now_iso8601_ms
from app.lib.ids import new_ulid
from app.slices.finance.models import (
    Account,
    Fund,
    Journal,
    JournalLine,
    Period,
    Project,
)


def _period_key_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _has_attr(model_cls, name: str) -> bool:
    return hasattr(model_cls, name)


def _gen_code(prefix: str, min_len: int = 6) -> str:
    u = new_ulid()
    return f"{prefix}{u[:max(min_len, 6)]}"


def _unique_code(model_cls, prefix: str, max_tries: int = 8) -> str:
    """
    Generate a unique code for `model_cls.code` by retrying with fresh ULIDs.
    Assumes model has a unique constraint on `code`.
    """
    assert _has_attr(model_cls, "code"), "Model doesn't have a `code` column."
    from sqlalchemy import select

    length = 6
    for _ in range(max_tries):
        code = _gen_code(prefix, length)
        exists = db.session.execute(
            select(model_cls).where(model_cls.code == code).limit(1)
        ).first()
        if not exists:
            return code
        # small bump to reduce collision risk if we keep hitting
        length = min(length + 1, 12)
    # last attempt; let DB catch if still collides
    return _gen_code(prefix, length)


def _safe_model_kwargs(
    model_cls, base: Dict[str, Any], *, code_prefix: Optional[str] = None
) -> Dict[str, Any]:
    """
    If model has 'code', add a unique code. Otherwise return base unchanged.
    Ensures 'ulid' exists in base.
    """
    out = dict(base)
    out.setdefault("ulid", new_ulid())
    if code_prefix and _has_attr(model_cls, "code"):
        out["code"] = _unique_code(model_cls, code_prefix)
    return out


def _ensure_account(code: str, name: str, type_: str) -> Account:
    a = Account.query.filter_by(code=code).one_or_none()
    if a:
        return a
    a = Account(ulid=new_ulid(), code=code, name=name, type=type_)
    db.session.add(a)
    db.session.commit()
    return a


def _ensure_fund_ulid(fund_ulid: Optional[str]) -> Fund:
    if fund_ulid:
        f = Fund.query.get(fund_ulid)
        if not f:
            raise click.ClickException(f"Fund ULID not found: {fund_ulid}")
        return f

    # Reuse an existing unrestricted fund if one exists (idempotent)
    q = Fund.query
    if _has_attr(Fund, "restriction"):
        q = q.filter_by(restriction="unrestricted")
    if _has_attr(Fund, "name"):
        q = q.filter_by(name="Unrestricted Operating Fund")
    f = q.first()
    if f:
        return f

    # Otherwise create a fresh unrestricted fund with a unique code if required
    kwargs = _safe_model_kwargs(
        Fund,
        {
            "name": "Unrestricted Operating Fund",
            "restriction": "unrestricted",
        },
        code_prefix="F-",
    )
    f = Fund(**kwargs)
    db.session.add(f)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        # Rare race/collision: retry with a new unique code
        kwargs = _safe_model_kwargs(
            Fund,
            {
                "ulid": new_ulid(),
                "name": "Unrestricted Operating Fund",
                "restriction": "unrestricted",
            },
            code_prefix="F-",
        )
        f = Fund(**kwargs)
        db.session.add(f)
        db.session.commit()
    return f


def _ensure_project_ulid(
    project_ulid: Optional[str], fund_ulid: Optional[str]
) -> Project:
    if project_ulid:
        p = Project.query.get(project_ulid)
        if not p:
            raise click.ClickException(
                f"Project ULID not found: {project_ulid}"
            )
        return p

    # Reuse an existing demo project if present (idempotent)
    q = Project.query
    if _has_attr(Project, "name"):
        q = q.filter_by(name="Welcome Home Kit")
    if _has_attr(Project, "fund_ulid") and fund_ulid:
        q = q.filter_by(fund_ulid=fund_ulid)
    p = q.first()
    if p:
        return p

    # Otherwise create it; include fund_ulid if the column exists
    base = {"name": "Welcome Home Kit"}
    if _has_attr(Project, "fund_ulid") and fund_ulid:
        base["fund_ulid"] = fund_ulid
    kwargs = _safe_model_kwargs(Project, base, code_prefix="P-")
    p = Project(**kwargs)
    db.session.add(p)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        kwargs = _safe_model_kwargs(
            Project, {"name": "Welcome Home Kit"}, code_prefix="P-"
        )
        if _has_attr(Project, "fund_ulid") and fund_ulid:
            kwargs["fund_ulid"] = fund_ulid
        p = Project(**kwargs)
        db.session.add(p)
        db.session.commit()
    return p


def _period_field_name() -> str | None:
    """Return the column name your Period model uses for the period identifier."""
    for cand in ("key", "period_key", "code", "label", "name"):
        if hasattr(Period, cand):
            return cand
    return None


def _set_attr_if_has(obj, name: str, value):
    if hasattr(obj, name):
        setattr(obj, name, value)


def _ensure_period(period_key: str) -> Period:
    # Figure out which column to use for the identifier
    ident_col = _period_field_name()

    # Try to find an existing period row
    if ident_col:
        pr = Period.query.filter(
            getattr(Period, ident_col) == period_key
        ).one_or_none()
        if pr:
            return pr

    # Create a new period row, setting whatever fields your model actually has
    pr = Period(ulid=new_ulid())
    if ident_col:
        _set_attr_if_has(pr, ident_col, period_key)

    # set status if your schema has it
    _set_attr_if_has(pr, "status", "open")

    db.session.add(pr)
    db.session.commit()
    return pr


def _post_demo_journal(period_key: str, lines: list[dict]) -> Journal:
    """
    Insert a small balanced journal for the given period.
    NOTE: Sets required NOT NULL fields per your finance_journal schema:
      - source (str)
      - currency (str)
      - period_key (str)
      - happened_at_utc (str, ISO-8601)
      - posted_at_utc (str, ISO-8601)
      - created_at_utc (str, ISO-8601)
    """
    now = now_iso8601_ms()
    j = Journal(
        ulid=new_ulid(),
        source="finance.cli.seed_demo",  # ← REQUIRED (NOT NULL)
        currency="USD",  # ← you can change default if needed
        period_key=period_key,  # ← REQUIRED
        happened_at_utc=now_iso8601_ms(),  # ← REQUIRED (NOT NULL)
        posted_at_utc=now,  # ← ok to set same for demo
        created_at_utc=now,  # ← set explicitly to avoid ORM inserting None
        memo="Seed demo journal",  # ← optional
        # created_by_actor can stay None if your column allows NULLs.
        # If it's NOT NULL, set to a known system actor ULID here.
        # created_by_actor="01SYS00000000000000000000",
    )
    db.session.add(j)
    db.session.flush()  # ensures j.ulid is available for FK

    for i, line in enumerate(lines, start=1):
        db.session.add(
            JournalLine(
                ulid=new_ulid(),
                journal_ulid=j.ulid,  # FK to Journal.ulid
                seq=i,
                account_code=line["account_code"],
                fund_code=line[
                    "fund_code"
                ],  # ← string code (REQUIRED by your model)
                project_ulid=line.get("project_ulid"),
                amount_cents=line["amount_cents"],
                period_key=period_key,  # ← REQUIRED by your model
                memo=line.get("memo"),
            )
        )


@click.group("finance")
def finance_group():
    """Finance slice commands (seed demo, etc.)."""
    ...


@finance_group.command("seed-demo")
@click.option(
    "--period",
    "period_key",
    default=None,
    help="YYYY-MM; defaults to current UTC month",
)
@click.option(
    "--fund-ulid",
    default=None,
    help="Existing fund ULID to use; create demo if omitted",
)
@click.option(
    "--project-ulid",
    default=None,
    help="Existing project ULID to use; create demo if omitted",
)
@with_appcontext
def seed_demo(
    period_key: str | None, fund_ulid: str | None, project_ulid: str | None
):
    """Seed a tiny ULID-based dataset so /finance/reports/activities renders."""
    echo_db_banner("seed-demo")
    period_key = period_key or _period_key_now()

    # reference COA (these are account CODES; OK to keep codes in COA)
    _ensure_account("1000", "Cash", "asset")
    _ensure_account("4100", "Contributions-Cash", "revenue")
    _ensure_account("5200", "Program Expense", "expense")

    fund = _ensure_fund_ulid(fund_ulid)
    proj = _ensure_project_ulid(project_ulid, fund.ulid)
    _ensure_period(period_key)

    # journal 1: cash in + revenue
    _post_demo_journal(
        period_key,
        [
            {
                "account_code": "1000",
                "fund_code": fund.code,  # ← use code
                "project_ulid": proj.ulid,
                "amount_cents": 250_00,
                "memo": "Seed: cash in",
            },
            {
                "account_code": "4100",
                "fund_code": fund.code,  # ← use code
                "project_ulid": proj.ulid,
                "amount_cents": 250_00,
                "memo": "Seed: donation",
            },
        ],
    )

    # journal 2: expense + cash out
    _post_demo_journal(
        period_key,
        [
            {
                "account_code": "5200",
                "fund_code": fund.code,  # ← use code
                "project_ulid": proj.ulid,
                "amount_cents": 110_00,
                "memo": "Seed: supplies",
            },
            {
                "account_code": "1000",
                "fund_code": fund.code,  # ← use code
                "project_ulid": proj.ulid,
                "amount_cents": 110_00,
                "memo": "Seed: cash out",
            },
        ],
    )

    click.echo(
        f"Seeded demo for {period_key} (fund={fund.ulid}, project={proj.ulid})."
    )


try:
    from app.slices.finance.services import (
        rebuild_balances as _svc_rebuild_balances,
    )
except Exception:
    _svc_rebuild_balances = None

try:
    from app.slices.finance.services import (
        set_period_status as _svc_set_period_status,
    )
except Exception:
    _svc_set_period_status = None


def _period_ident_field() -> Optional[str]:
    for cand in ("key", "period_key", "code", "label", "name"):
        if hasattr(Period, cand):
            return cand
    return None


@finance_group.command("close-period")
@click.argument("period_key")
@with_appcontext
def close_period(period_key: str):
    """Mark a period closed (uses service if available; otherwise falls back)."""
    # Try service if present and compatible
    echo_db_banner("close-period")
    if _svc_set_period_status:
        try:
            sig = signature(_svc_set_period_status)
            params = list(sig.parameters.values())
            # Accept common shapes: (period_key, status) or (period_key, status, **kwargs)
            if len(params) >= 2 and params[0].kind in (
                Parameter.POSITIONAL_ONLY,
                Parameter.POSITIONAL_OR_KEYWORD,
            ):
                _svc_set_period_status(period_key, "closed")
                click.echo(f"Closed via service: {period_key}")
                return
        except Exception as e:
            click.echo(
                f"Service set_period_status not used (reason: {e}). Falling back.",
                err=True,
            )

    # Fallback: update Period row directly (schema-adaptive)
    ident = _period_ident_field()
    if not ident:
        raise click.ClickException(
            "Period identifier column not found on model."
        )

    pr = Period.query.filter(
        getattr(Period, ident) == period_key
    ).one_or_none()
    if not pr:
        pr = Period(ulid=new_ulid())
        setattr(pr, ident, period_key)
        if hasattr(pr, "status"):
            pr.status = "closed"
        db.session.add(pr)
    else:
        if hasattr(pr, "status"):
            pr.status = "closed"
    db.session.commit()
    click.echo(f"Closed via fallback: {period_key}")


@finance_group.command("rebuild-balances")
@click.option(
    "--from", "period_from", required=True, help="YYYY-MM start (inclusive)"
)
@click.option(
    "--to", "period_to", required=True, help="YYYY-MM end (inclusive)"
)
@with_appcontext
def rebuild_balances_cmd(period_from: str, period_to: str):
    """Rebuild monthly balances projection for a range (uses service if available; otherwise no-op)."""
    echo_db_banner("rebuild-balances")
    if _svc_rebuild_balances:
        try:
            # Prefer explicit kwargs; many services use this exact signature
            res = (
                _svc_rebuild_balances(
                    period_from=period_from, period_to=period_to
                )
                or {}
            )
            click.echo(
                f"Rebuilt via service: rows={res.get('rows','?')} for {period_from}..{period_to}"
            )
            return
        except TypeError as e:
            # Signature mismatch (or it called event_bus.emit with unexpected kwargs)
            click.echo(
                f"Service rebuild_balances failed ({e}). No-op fallback.",
                err=True,
            )
        except Exception as e:
            click.echo(
                f"Service rebuild_balances raised {type(e).__name__}: {e}. No-op fallback.",
                err=True,
            )

    # Fallback: keep it safe (no-op/notice)
    click.echo("rebuild_balances service not available/compatible; no-op.")
