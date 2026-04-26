# app/slices/admin/toolbox.py

from __future__ import annotations

from urllib.parse import urlparse

from flask import current_app, render_template, request, url_for
from flask_login import login_required

from app.lib.security import roles_required

from .routes import bp


def _paramfree_get_routes() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for rule in current_app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        if "GET" not in (rule.methods or set()):
            continue
        if rule.arguments:
            continue

        endpoint = rule.endpoint
        try:
            href = url_for(endpoint)
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


def _as_path(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        parsed = urlparse(href)
        if parsed.query:
            return f"{parsed.path}?{parsed.query}"
        return parsed.path
    return href


def _probe_routes(
    routes: list[dict[str, str]],
) -> dict[str, dict[str, str | int | bool]]:
    """
    Probe each param-free GET route using Flask's test client.
    Returns: endpoint -> {ok, status, location}
    """
    PROBE_EXCLUDE_BLUEPRINTS = {"admin"}
    PROBE_EXCLUDE_ENDPOINT_PREFIXES = {"auth.dev_"}

    client = current_app.test_client()

    sentinel = object()
    prev = current_app.config.get("PROPAGATE_EXCEPTIONS", sentinel)
    current_app.config["PROPAGATE_EXCEPTIONS"] = False

    try:
        out: dict[str, dict[str, str | int | bool]] = {}
        for row in routes:
            endpoint = row["endpoint"]
            bpname = row.get("blueprint") or endpoint.split(".", 1)[0]
            href = _as_path(row["href"])

            if (
                endpoint == "admin.dev_toolbox"
                or href == "/admin/dev_toolbox/"
            ):
                continue
            if bpname in PROBE_EXCLUDE_BLUEPRINTS:
                out[endpoint] = {
                    "ok": False,
                    "status": -1,
                    "location": "skipped",
                }
                continue
            if any(
                endpoint.startswith(prefix)
                for prefix in PROBE_EXCLUDE_ENDPOINT_PREFIXES
            ):
                continue

            try:
                resp = client.get(href, follow_redirects=False)
                status = int(resp.status_code)
                loc = resp.headers.get("Location") or ""
                ok = 200 <= status < 300
                out[endpoint] = {
                    "ok": ok,
                    "status": status,
                    "location": loc,
                }
            except Exception as exc:
                out[endpoint] = {
                    "ok": False,
                    "status": 0,
                    "location": exc.__class__.__name__,
                }
        return out
    finally:
        if prev is sentinel:
            current_app.config.pop("PROPAGATE_EXCEPTIONS", None)
        else:
            current_app.config["PROPAGATE_EXCEPTIONS"] = prev


# VCDB-SEC: ACTIVE entry=admin authority=admin-only reason=admin_only_surface
@bp.get("/dev_toolbox/")
@login_required
@roles_required("admin")
def dev_toolbox():
    env = (current_app.config.get("ENV") or "").lower()
    routes = _paramfree_get_routes()
    probes = None
    if request.args.get("probe") == "1":
        probes = _probe_routes(routes)

    return render_template(
        "admin/dev_toolbox.html",
        env=env,
        routes=routes,
        probes=probes,
    )
