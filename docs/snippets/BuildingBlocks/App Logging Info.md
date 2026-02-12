# App Logging Info

# 1) Make logging idempotent

```python
def reset_logger(lg):
    for h in list(lg.handlers):
        lg.removeHandler(h)
```

- Before adding new handlers, it **removes any existing handlers** from a logger.

- This prevents duplicate log lines when your app factory (`create_app`) is called multiple times (common in tests and CLI tools).

# 2) Choose output **target** based on environment

- **Dev (ENV=development and not TESTING)** → write **JSON lines** to files in `app/logs/`.

- **Everything else** (prod, staging, tests) → write **JSON lines** to **stdout** (container-friendly).

That’s what this branch decides:

```python
is_dev = app.config.get("ENV") == "development" and not app.testing
```

# 3) In Dev: wire **file handlers** per logger

It creates a helper that returns a file handler with a JSON formatter:

```python
def fh(filename):
    h = logging.FileHandler(log_dir / filename, encoding="utf-8")
    h.setFormatter(JSONLineFormatter())
    h.setLevel(logging.INFO)
    return h
```

Then it attaches those:

**a) Flask’s app logger**

```python
reset_logger(app.logger)
app.logger.setLevel(logging.INFO)
app.logger.addHandler(fh("app.log"))
```

- The app logger writes to `app/logs/app.log`.

**b) Framework loggers**

```python
for name in ("werkzeug", "jinja2"):
    lg = logging.getLogger(name)
    reset_logger(lg)
    lg.addHandler(fh("app.log"))
    lg.setLevel(logging.INFO if name == "werkzeug" else logging.ERROR)
```

- Routes/access logs from Werkzeug → `app.log` at INFO.

- Jinja2 template warnings/errors → `app.log`, but only ERROR and above (cuts noise).

**c) Domain loggers (your “namespaces”)**

```python
for name, file in (
    ("vcdb.app",   "app.log"),
    ("vcdb.audit", "audit.log"),
    ("vcdb.jobs",  "jobs.log"),
    ("vcdb.export","export.log"),
):
    lg = logging.getLogger(name)
    reset_logger(lg)
    lg.setLevel(logging.INFO)
    lg.addHandler(fh(file))
    lg.propagate = False
```

- You can write to these with:
  
  - `logging.getLogger("vcdb.app").info(...)`
  
  - `logging.getLogger("vcdb.audit").info(...)`, etc.

- Each goes to its own file (except `vcdb.app`, which shares `app.log`).

- `propagate = False` means “don’t bubble up to parent loggers,” avoiding duplicate lines in `app.log`.

# 4) In Non-Dev: wire **one stdout handler** (JSON)

```python
root = logging.getLogger()
reset_logger(root)
sh = logging.StreamHandler()
sh.setFormatter(JSONLineFormatter())
sh.setLevel(logging.INFO)
root.addHandler(sh)
root.setLevel(logging.INFO)
```

- Everything logs to **stdout** as JSON (ideal for Docker/Kubernetes log collection).

- Tone down framework chatter:

```python
logging.getLogger("werkzeug").setLevel(logging.WARNING)
logging.getLogger("jinja2").setLevel(logging.ERROR)
```

---

## Why it feels complex (and why it’s useful)

- It’s **centralized**: one function sets up the whole logging topology.

- It’s **idempotent**: safe even if the app is created multiple times.

- It’s **environment-aware**: files in dev for human inspection; stdout elsewhere for infra.

- It’s **namespaced**: `vcdb.audit`, `vcdb.jobs`, etc., so you can route domain logs to different files.

---

## How you’ll use it day-to-day

- For **audit** events:
  
  ```python
  logging.getLogger("vcdb.audit").info({
      "event": "login_success",
      "actor": user.entity_ulid,
      "request_id": g.request_id,
  })
  ```

- For **batch/cron**:
  
  ```python
  logging.getLogger("vcdb.jobs").info({"job": "nightly-role-repair", "status": "started"})
  ```

- For **app-level**:
  
  ```python
  logging.getLogger("vcdb.app").info({"msg": "entity_created", "entity": ulid})
  ```

All of these will be JSON lines with whatever fields you pass, plus whatever your `JSONLineFormatter()` includes (timestamp, level, logger name, etc.).

---

## Small sanity checks / tips

- Make sure `JSONLineFormatter` **never throws** (bad formatters can crash logging).

- Confirm `LOG_DIR` is writable in dev; prod/staging ignore it (stdout).

- If you ever see **duplicate lines**, a logger probably has `propagate=True` **and** a handler on a parent logger—flip `propagate=False` on the child, or remove the parent handler.

- In tests, since `app.testing=True`, everything goes to stdout; if you want **no logging** in tests, you can set level to `CRITICAL` in your test config.

That’s it. The function is basically a clean, defensive “router” that sets where logs flow and at what volume—files in dev, stdout elsewhere, namespaced for domain clarity, with idempotency baked in.
