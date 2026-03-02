# CSRF Audit

Yep — you can avoid a manual audit. Do it in **two passes**: (1) a mechanical  
repo-wide grep to find the places that need CSRF/macros, (2) fix the highest  
value forms first, then let a lightweight “template lint” catch the rest.

## 1) Fast inventory (no edits yet)

Run these from repo root:

```bash
# All templates that POST
rg -n --glob='**/*.html' '<form[^>]*method="post"' app/templates app/slices

# Templates already importing your macros
rg -n --glob='**/*.html' '{% *import "_macros\.html" as macros *%}' app/templates app/slices

# Templates that call csrf_token directly (normalize them)
rg -n --glob='**/*.html' 'csrf_token\(' app/templates app/slices

# Templates that already include a csrf_token hidden input
rg -n --glob='**/*.html' 'name="csrf_token"' app/templates app/slices
```

That gives you a clean hit list without reading files.

## 2) Add CSRF *mechanically* where missing (semi-automated)

### A) Minimal rule of thumb

For any template with `<form method="post">`:

- ensure it has `{{ macros.csrf_field() }}` inside the form

- ensure it has `{% import "_macros.html" as macros %}` near the top

### B) Use a targeted “apply-by-pattern” approach

If you’re comfortable doing one mechanical edit, do it slice-by-slice  
(Resources, Sponsors, Customers…).

Example approach:

- open each file from the `rg '<form.*method="post"'` list

- if missing, add the import line once at top (after `{% extends ... %}`)

- insert `{{ macros.csrf_field() }}` as the first line inside each POST form

This is still “manual”, but it’s **guided** and fast because `rg` gives you the  
exact list.

## 3) Catch regressions automatically with a tiny template lint (recommended)

Add a dev-only CLI command that scans templates and warns when a POST form  
doesn’t include CSRF.

Example (drop into an existing dev cli module like `app/cli_dev.py`):

```python
# dev-only: template csrf audit
from __future__ import annotations

import re
from pathlib import Path

import click

FORM_POST_RE = re.compile(r"<form[^>]*method=[\"']post[\"'][^>]*>", re.I)
CSRF_RE = re.compile(r'name=[\"\\\']csrf_token[\"\\\']|csrf_field\\(', re.I)

@click.command("template-csrf-audit")
def template_csrf_audit():
    roots = [
        Path("app/templates"),
        Path("app/slices"),
    ]
    offenders = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.html"):
            txt = p.read_text(errors="ignore")
            if not FORM_POST_RE.search(txt):
                continue
            # if it posts, it needs csrf (either via macros.csrf_field() or raw hidden input)
            if not CSRF_RE.search(txt):
                offenders.append(str(p))

    if offenders:
        click.echo("POST forms missing CSRF:")
        for f in offenders:
            click.echo(f"  - {f}")
        raise SystemExit(1)

    click.echo("OK — all POST forms appear to include CSRF.")
```

Run it whenever you touch templates:

```bash
flask dev template-csrf-audit
```

This turns the “major chore” into a **checklist** the tool enforces for you.

## 4) Optional safety net: add a global runtime check in dev

If CSRF is enabled via Flask-WTF, missing tokens usually 400 anyway. But if  
some forms aren’t protected for any reason, the lint still flags them.

---

### My suggested execution order

1. Run `rg` inventory.

2. Fix Resources/Sponsors/Customers onboarding + wizards (highest value).

3. Add the `template-csrf-audit` dev command.

4. Use the audit output to chip away at the rest over time.

If you paste the output of `rg '<form.*method="post"'` (just the filenames, no  
content), I can tell you which ones are likely already CSRF-safe vs which ones  
need edits first.
