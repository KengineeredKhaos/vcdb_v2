"""
Sweep all parameter-free GET routes through the real auth flow for a small
operator matrix, report HTTP status codes, and flag suspicious responses.

Intended use:
    python tools/route_access_sweep.py --env dev

This script:
- builds the Flask app with development DB/settings
- forcibly disables stub/dev auto-login conveniences for the sweep
- disables CSRF only for the scripted login POSTs
- logs in as each seeded operator through /auth/login
- probes each parameter-free GET route with a fresh client per operator
- prints a summary and writes CSV/JSON reports

It does NOT mutate code or require the old stub scaffold.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Make repo root importable when this file is run as:
#   python tools/route_access_sweep.py --env dev
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import DevConfig, TestConfig
from app import create_app as create_flask_app
from manage_vcdb import prepare_runtime_env


def build_app(env: str):
    _, cfg_object = prepare_runtime_env(env)
    app = create_flask_app(config_object=cfg_object)

    # force sweep-friendly overrides here if needed
    app.config["AUTH_MODE"] = "real"
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["ALLOW_HEADER_AUTH"] = False
    app.config["AUTO_LOGIN_ADMIN"] = False
    app.config["ALLOW_DEV_STUB_AUTH"] = False

    return app


@dataclass(frozen=True)
class SweepUser:
    label: str
    username: str
    password: str
    role: str


BOOTSTRAP_USERS: tuple[SweepUser, ...] = (
    SweepUser(
        label="admin",
        username="admin.op",
        password="adminuser",
        role="admin",
    ),
    SweepUser(
        label="staff",
        username="staff.op",
        password="staffuser",
        role="staff",
    ),
    SweepUser(
        label="auditor",
        username="auditor.read",
        password="audituser",
        role="auditor",
    ),
)


@dataclass(frozen=True)
class RouteRow:
    user_label: str
    user_role: str
    endpoint: str
    blueprint: str
    path: str
    status: int
    category: str
    location: str
    flagged: bool


class SweepConfig(DevConfig):
    """Dev DB, real auth, no auto-stub conveniences."""

    AUTH_MODE = "real"
    ALLOW_HEADER_AUTH = False
    AUTO_LOGIN_ADMIN = False
    ALLOW_DEV_STUB_AUTH = False
    WTF_CSRF_ENABLED = False
    DEV_BOOT_DIAG = False
    DEV_BOOT_SANITY = False
    DEV_POLICY_FINGERPRINT = False
    DEV_POLICY_FINGERPRINT_LIST = False
    DEV_POLICY_HEALTH = False
    DEV_POLICY_HEALTH_LIST = False
    DEV_SCHEMA_CHECK = False
    DEV_SCHEMA_CHECK_DEEP = False


class SweepTestConfig(TestConfig):
    """Optional if you want to point the sweep at test env later."""

    AUTH_MODE = "real"
    ALLOW_HEADER_AUTH = False
    AUTO_LOGIN_ADMIN = False
    WTF_CSRF_ENABLED = False


def _as_path(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        u = urlparse(href)
        return f"{u.path}?{u.query}" if u.query else u.path
    return href


def _paramfree_get_routes(app) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        if "GET" not in (rule.methods or set()):
            continue
        if rule.arguments:
            continue

        endpoint = rule.endpoint
        try:
            href = app.url_for(endpoint)
        except Exception:
            href = rule.rule

        bpname = endpoint.split(".", 1)[0] if "." in endpoint else ""
        rows.append(
            {
                "href": href,
                "path": rule.rule,
                "endpoint": endpoint,
                "blueprint": bpname,
            }
        )

    rows.sort(key=lambda r: (r["blueprint"], r["path"], r["endpoint"]))
    return rows


def _category_for(status: int) -> tuple[str, bool]:
    if 200 <= status < 300:
        return "OK", False
    if 300 <= status < 400:
        return "REDIRECT", False
    if status in {401, 403}:
        return "DENIED", False
    return "BAD", True


def _login(client, user: SweepUser) -> None:
    resp = client.post(
        "/auth/login",
        data={
            "username": user.username,
            "password": user.password,
        },
        follow_redirects=False,
    )
    if resp.status_code not in {200, 302, 303}:
        raise RuntimeError(
            f"Login failed for {user.username}: HTTP {resp.status_code}"
        )


def _sweep_user(app, user: SweepUser) -> list[RouteRow]:
    client = app.test_client()
    _login(client, user)

    rows: list[RouteRow] = []
    for route in _paramfree_get_routes(app):
        href = _as_path(route["href"])
        try:
            resp = client.get(href, follow_redirects=False)
            status = int(resp.status_code)
            location = resp.headers.get("Location") or ""
        except Exception as exc:
            status = 0
            location = exc.__class__.__name__

        category, flagged = _category_for(status)
        rows.append(
            RouteRow(
                user_label=user.label,
                user_role=user.role,
                endpoint=route["endpoint"],
                blueprint=route["blueprint"],
                path=route["path"],
                status=status,
                category=category,
                location=location,
                flagged=flagged,
            )
        )
    return rows


def _write_csv(rows: list[RouteRow], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "user_label",
                "user_role",
                "endpoint",
                "blueprint",
                "path",
                "status",
                "category",
                "location",
                "flagged",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _write_json(rows: list[RouteRow], path: Path) -> None:
    payload = [asdict(row) for row in rows]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _print_summary(rows: list[RouteRow]) -> None:
    by_user: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_user.setdefault(
            row.user_label,
            {"OK": 0, "REDIRECT": 0, "DENIED": 0, "BAD": 0},
        )
        bucket[row.category] = bucket.get(row.category, 0) + 1

    print("\nRoute sweep summary")
    print("===================")
    for user_label, counts in by_user.items():
        print(
            f"{user_label:8} "
            f"OK={counts.get('OK', 0):3d}  "
            f"REDIRECT={counts.get('REDIRECT', 0):3d}  "
            f"DENIED={counts.get('DENIED', 0):3d}  "
            f"BAD={counts.get('BAD', 0):3d}"
        )

    bad_rows = [row for row in rows if row.flagged]
    print("\nFlagged responses")
    print("=================")
    if not bad_rows:
        print("None")
        return

    for row in bad_rows:
        print(
            f"[{row.user_label}/{row.user_role}] "
            f"{row.status:>3} {row.endpoint:<40} {row.path}"
        )
        if row.location:
            print(f"    location: {row.location}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sweep real-auth GET routes")
    parser.add_argument(
        "--env",
        default="dev",
        choices=["dev", "development", "test", "testing"],
        help="App config to use for the sweep",
    )
    parser.add_argument(
        "--outdir",
        default="app/instance/route_sweep",
        help="Directory for CSV/JSON output",
    )
    args = parser.parse_args(argv)

    app = build_app(args.env)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    all_rows: list[RouteRow] = []
    with app.app_context():
        for user in BOOTSTRAP_USERS:
            all_rows.extend(_sweep_user(app, user))

    csv_path = outdir / "route_access_sweep.csv"
    json_path = outdir / "route_access_sweep.json"
    _write_csv(all_rows, csv_path)
    _write_json(all_rows, json_path)
    _print_summary(all_rows)

    print("\nWrote:")
    print(f"  CSV : {csv_path}")
    print(f"  JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
