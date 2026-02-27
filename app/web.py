# app/web.py
from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, current_app, render_template, request, url_for

bp = Blueprint("web", __name__)


def _paramfree_get_routes() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for rule in current_app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        if "GET" not in (rule.methods or set()):
            continue
        if rule.arguments:  # excludes "/x/<id>"
            continue

        endpoint = rule.endpoint
        try:
            href = url_for(endpoint)
        except Exception:
            # Still show it; may be host/subdomain quirks.
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
    # url_for() normally returns "/path". If it returns an absolute URL,
    # strip to just the path+query so test_client can use it.
    if href.startswith("http://") or href.startswith("https://"):
        u = urlparse(href)
        if u.query:
            return f"{u.path}?{u.query}"
        return u.path
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

    # Make probing resilient: don't let route exceptions blow up the portal.
    sentinel = object()
    prev = current_app.config.get("PROPAGATE_EXCEPTIONS", sentinel)
    current_app.config["PROPAGATE_EXCEPTIONS"] = False

    try:
        out: dict[str, dict[str, str | int | bool]] = {}
        for r in routes:
            endpoint = r["endpoint"]
            bpname = r.get("blueprint") or endpoint.split(".", 1)[0]
            href = _as_path(r["href"])

            # Avoid probing the portal itself and spiraling.
            if endpoint == "web.index" or href == "/":
                continue
            if bpname in PROBE_EXCLUDE_BLUEPRINTS:
                out[endpoint] = {
                    "ok": False,
                    "status": -1,
                    "location": "skipped",
                }
                continue
            if any(
                endpoint.startswith(p)
                for p in PROBE_EXCLUDE_ENDPOINT_PREFIXES
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
                    "location": f"{exc.__class__.__name__}",
                }
        return out
    finally:
        # Restore prior behavior.
        if prev is sentinel:
            current_app.config.pop("PROPAGATE_EXCEPTIONS", None)
        else:
            current_app.config["PROPAGATE_EXCEPTIONS"] = prev  # type: ignore[assignment]


@bp.get("/")
def index():
    env = (current_app.config.get("ENV") or "").lower()
    if env in {"dev", "development", "test", "testing"}:
        routes = _paramfree_get_routes()
        probes = None
        if request.args.get("probe") == "1":
            probes = _probe_routes(routes)

        return render_template(
            "layout/index_dev.html",
            env=env,
            routes=routes,
            probes=probes,
        )

    # prod: use the real template
    return render_template("layout/index.html")
