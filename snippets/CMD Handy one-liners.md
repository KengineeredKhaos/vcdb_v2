# Handy one-liners

## JSON / YAML

- Pretty-print (and fail fast):
  
  ```
  python -m json.tool app/slices/governance/data/policy_issuance.json >/dev/null
  ```

- Canonicalize + sort keys (great for diffs):
  
  ```
  jq -S . policy_issuance.json > /tmp/x && mv /tmp/x policy_issuance.json
  ```

- Validate against a schema (no extra script needed):
  
  ```
  python - <<'PY'
  import json, sys
  from jsonschema import Draft202012Validator
  payload=json.load(open(sys.argv[1]))
  schema=json.load(open(sys.argv[2]))
  Draft202012Validator(schema).validate(payload)
  print("OK")
  PY policy_issuance.json policy_issuance.schema.json
  ```

- YAML↔JSON (if you install yq):
  
  ```
  yq -o=json '.rules[].match' policy_issuance.yaml
  ```

# Grep / ripgrep / sed

### RipGrep basic shape

```
rg [OPTIONS] <pattern> [<path>...]
```

- `<pattern>` = what to search for (quote it if it has spaces or shell chars)

- `<path>` = file or directory (omit → search current directory)

### quick examples

```bash
rg "search"                # search recursively in .
rg "search" src/           # search only in the src/ directory
rg "search phrase" file.txt
rg -e "--flag-looking-text" -g "*.md"    # -e lets patterns start with '-'
```

### common flags

**output & formatting**

- `-n, --line-number` — show line numbers (use `--no-line-number` to hide)

- `-H, --with-filename` / `-h` — force show / hide filenames

- `--color=auto|always|never` — colorize matches

**matching behavior**

- `-i` — ignore case

- `-S` — smart case (case-insensitive unless pattern has uppercase)

- `-w` — match whole words

- `-F` — treat pattern as a literal string (no regex)

- `-v` — invert match (show non-matching lines)

- `-o` — print only the matching part of the line

- `-c` — count matches (per file)

- `-l` — list only filenames with a match

**context around matches**

- `-C N` — N lines of context (before & after)

- `-A N` — N lines **after**

- `-B N` — N lines **before**

**which files to search**

- `--hidden` — include dotfiles/directories

- `--no-ignore` — ignore .gitignore and other ignore files

- `-g "GLOB"` — include/exclude via glob (repeatable), e.g. `-g "*.rs" -g "!target/"`

- `--max-depth N` — limit recursion depth

**regex engine**

- `-F` — (again) fixed strings, fastest for plain text

- `-P` — use PCRE2 for advanced regex features

### tiny mental model

- put the **search pattern right after options**, then **files/dirs**:  
  `rg [opts] "pattern" [file-or-dir ...]`

That’s it—short, sharp, and handy.

- Show filenames only (fast project search):
  
  ```
  rg -l 'decide_issue\(' app/
  ```

- Confirm replacements before doing them:
  
  ```
  rg -n 'p\["qual"\]' app/ | sed 's/^/PREVIEW: /'
  ```

- Safe in-place change (GNU sed):
  
  ```
  sed -i 's/old/new/g' $(rg -l 'old' app/)
  ```

## Quick data pokes

- SQLite peek:
  
  ```
  sqlite3 var/app-instance/dev.db '.tables'
  sqlite3 var/app-instance/dev.db 'PRAGMA foreign_keys=ON; SELECT COUNT(*) FROM logi_issue;'
  ```

- Diff two JSONs semantically (ignoring key order):
  
  ```
  diff <(jq -S . a.json) <(jq -S . b.json)
  ```

## Flask / Click

- View all CLI commands you wired:
  
  ```
  flask --help | sed -n '/Commands:/,$p'
  ```

- Run a command with app context imports printed (helps trace ImportErrors):
  
  ```
  FLASK_DEBUG=1 flask dev policy-health -v
  ```

## Alembic / Migrate

- See migration graph head:
  
  ```
  flask db heads
  ```

- Check current DB rev:
  
  ```
  flask db current
  ```

- Autogenerate but **don’t** apply yet:
  
  ```
  flask db migrate -m "note" && rg -n 'upgrade|downgrade' migrations/versions/*note*.py
  ```

## Pytest speedups

- Fail fast + last-failed:
  
  ```
  pytest -q -x --last-failed
  ```

- Run a test every time a file changes (needs `entr`):
  
  ```
  rg -l 'decide_issue' app/ | entr -r pytest -q tests/test_enforcers.py::test_calendar_blackout_ok_blocked
  ```

## ULID / Time one-liners

- Generate a ULID:
  
  ```
  python - <<'PY'
  from ulid import ULID; print(ULID())
  PY
  ```

- UTC “now” ISO (using Python, consistent with our chrono utils):
  
  ```
  python - <<'PY'
  from datetime import datetime, timezone
  print(datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z"))
  PY
  ```

## Git ergonomics

- Diff JSON canonically:
  
  ```
  git difftool -y --tool=meld  # or use jq -S pre-commit filter
  ```

- Only show files you actually touched in app/:
  
  ```
  git diff --name-only main -- app/
  ```

## Quick servers / sanity

- Serve a folder (handy to eyeball static docs):
  
  ```
  python -m http.server -d app/slices/governance/static 8080
  ```

## Process hygiene

- See what’s holding the dev DB (Linux):
  
  ```
  lsof var/app-instance/dev.db
  ```

If any of these should be turned into Make targets (e.g., `make policy-health`, `make test-fast`), say the word and I’ll sketch a tiny `Makefile` that wraps them so your fingers type less.
