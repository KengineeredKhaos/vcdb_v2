# U.I. Development Plan

1. Decide the minimal shell
- `templates/layout/base.html` with StrictUndefined and a single `{% block content %}`

- `templates/layout/_nav.html`, `_flash.html`, `_footer.html`

- One app-wide CSS (or keep your existing) referenced via `url_for('static', ...)`
2. Slice-first template placement
- Keep templates inside each slice:  
  `app/slices/<slice>/templates/<slice>/*.html`

- Only shared layout/partials under `app/templates/layout/` (no slice logic there)
3. Dev guardrails to keep templates honest
- Jinja `StrictUndefined` on (already your default)

- Inline field errors under inputs (per your project canon)

- No PII in logs/rendered debug; domain/RBAC shown only when explicitly toggled
4. Boilerplate we’ll drop into canvas (when you say “go”)
- `base.html` (skinny, production-ready structure)

- `_nav.html` with role-aware links, but **read-only** unless `admin+governor`

- `_flash.html` (single include)

- A tiny `index.html` using the layout to prove wiring

- Optional `policy_index.html` & `policy_view.html` that consume the already-pinned governance contracts (read-only to start)
5. Lightweight UI testing
- Add a foundation test that `GET /` renders and that the nav hides admin links without admin+governor

- Snapshot tests for the governance policies JSON → template (no mutation)

When you’re ready to kick off, just say “create the UI canvas,” and I’ll scaffold the files there so you can iterate fast and download in one click.
