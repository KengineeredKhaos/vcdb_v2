You’re dead on about Finance needing to be “boring, uniform, canonical.” Let’s treat this reply as the **Lego spec** for Finance (and future slices), grounded in the files you just uploaded.

I’ll do three things:

1. Lock in the **ContractError / wrapper Lego** (using what you already have in `errors.py` + `sponsors_v2`).

2. Define **Service-internal error Lego**, **DTO Lego**, **Contract Lego**, and **Service Lego** as copy-pasteable patterns.

3. Show how this applies specifically to **Finance v2** (log_expense today; log_donation later).

---

## 1. ContractError + wrapper Lego (canonical)

### Canonical shape

You already have a really clear canonical definition for `ContractError` in `app/extensions/errors.py`: it has `code`, `where`, `message`, `http_status`, and optional `data`.

Key semantics from that file:

- Raised **only at contract boundary** (`app/extensions/contracts/*`).

- `code` = short machine code, e.g. `"bad_argument"`, `"not_found"`.

- `where` = fully-qualified contract function (`"finance_v2.log_donation"`).

- `message` = one-line operator-friendly clue.

- `data` = small extra payload (ULIDs, keys, counts), PII-free.

That already matches what you just said you want: **real clue in `message`, structured details in `data`.**

### Standard wrapper mapping (`_as_contract_error`)

Sponsors v2 already has a **very good** `_as_contract_error` helper that maps common Python exception types into standard ContractError codes:

- `ValueError` → `bad_argument` (400)

- `PermissionError` → `permission_denied` (403)

- `LookupError` → `not_found` (404)

- Anything else → `internal_error` (500) with `exc_type` in `data`.

That’s exactly the Lego we want to reuse in **every** contract module, including Finance.

**Lock-in proposal (canonical for all v2 contracts):**

- Every `*_v2` contract module defines **the same `_as_contract_error(where, exc)`** (copy from `sponsors_v2` now; we can later DRY it into a shared helper if you want).

- Contracts always do:
  
  ```python
  where = "finance_v2.log_donation"
  try:
      ...
      return <DTO or dict>
  except Exception as exc:
      raise _as_contract_error(where, exc)
  ```

- “Real info” goes in `exc` message; we don’t invent error text at the wrapper layer except for the generic `internal_error` fallback.

That gives you **uniform error codes**, **consistent http_status**, and **per-site messages/data** without inventing a new error framework.

---

## 2. Lego shapes for this project

### 2.1 Service-internal Error Lego

You don’t actually need a fancy hierarchy here. Sponsors services already get good mileage out of **plain Python exceptions**:

- `ValueError` → bad arguments or impossible semantic states

- `LookupError` → “not found”

- `PermissionError` → “you’re not allowed to do that”

Those types are already understood by `_as_contract_error` in Sponsors.

**Service Error Lego (per slice):**

- In each slice’s `services.py`, you can:
  
  ```python
  class FinanceError(Exception):
      """Base for finance-specific semantics, if we need it."""
      pass
  
  class PolicyViolation(FinanceError, ValueError):
      """Finance-specific semantic/validation problems."""
      pass
  ```

- But **90% of the time**, just raising:
  
  - `ValueError("amount_cents must be > 0")`
  
  - `LookupError("fund not found")`
  
  - `PermissionError("actor lacks role 'treasurer'")`

  is enough. The contract wrapper knows how to translate these.

So your **Service Error Lego** is:

> “Services throw `ValueError`, `LookupError`, or `PermissionError` (or a tiny slice-specific subclass thereof). Contracts catch them and map them to `ContractError` with standard codes.”

No extra contract-scope error classes required.

---

### 2.2 DTO Lego

You already have a solid DTO pattern in `finance_v2.py`: simple `@dataclass` with typed fields, no methods.

Example (ExpenseDTO):

```python
@dataclass
class ExpenseDTO:
    id: str
    fund_id: str
    project_id: str
    occurred_on: str
    vendor: str
    amount_cents: int
    category: str
    approved_by_ulid: Optional[str] = None
    flags: List[str] = None
```

That’s perfect.

**DTO Lego rule:**

- One DTO **per pipeline** is fine (even preferred).

- Use `@dataclass` + plain fields (`str/int/bool/list/dict/Optional[...]`).

- No DB session, no business logic methods.

- Services are free to construct DTOs; contracts just pass them back out.

TypedDict (like `DonationDTO` in your latest finance_v2 draft) is also fine when you want dict semantics, but we don’t *need* it as long as the `@dataclass` is working for you.

---

### 2.3 Contract Lego (for Finance and friends)

Right now, `finance_v2` is still “dict payload in, DTO out” with almost no contract-layer shape checking and no `_as_contract_error` mapping (except a one-off in `get_fund_summary`).

You said you want:

- **Typed arguments** at contract layer.

- **Shape checking** (ULIDs, ints, basic presence) in the contract.

- **Semantic validation** (does the fund exist, is period open) in the service.

- **Consistent ContractError** wrapper.

So let’s define a **Finance Contract Lego** you can copy for every Finance entry point:

```python
# app/extensions/contracts/finance_v2.py

from app.extensions.errors import ContractError
from app.lib.ids import new_ulid
from app.slices.finance import services as svc

# ... DTOs + _as_contract_error + _require_* helpers up here ...


def log_expense(
    *,
    fund_ulid: str,
    project_ulid: str,
    amount_cents: int,
    occurred_on: str,
    category: str,
    vendor: str | None = None,
    request_id: str | None = None,
    actor_ulid: str | None = None,
    dry_run: bool = False,
) -> ExpenseDTO:
    where = "finance_v2.log_expense"
    try:
        fund_ulid = _require_ulid("fund_ulid", fund_ulid)
        project_ulid = _require_ulid("project_ulid", project_ulid)
        amount_cents = _require_int_ge("amount_cents", amount_cents, minval=1)
        category = _require_str("category", category)
        vendor = (vendor or "").strip()

        if request_id is None:
            request_id = new_ulid()
        else:
            request_id = _require_ulid("request_id", request_id)

        return svc.log_expense(
            fund_ulid=fund_ulid,
            project_ulid=project_ulid,
            amount_cents=amount_cents,
            occurred_on=occurred_on,
            category=category,
            vendor=vendor,
            request_id=request_id,
            actor_ulid=actor_ulid,
            dry_run=dry_run,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc)
```

Where `_require_str`, `_require_ulid`, `_require_int_ge`, and `_as_contract_error` are **cloned from `sponsors_v2`** (one per contract module).

That gives you:

- Typed args, keyword-only.

- Lightweight shape checking at the boundary.

- Domain semantics in `svc.log_expense`.

- ContractError as the only thing that escapes when something goes wrong.

We’d refactor all the current `def log_expense(payload: dict, ...)` style functions in `finance_v2.py` to look like this.

---

### 2.4 Service Lego (Finance version)

Your `log_expense` service today already looks close to a nice “Service Lego”: it takes a payload dict, extracts required fields, validates, posts a journal, emits an event, and returns an `ExpenseDTO`.

For new Finance services (including a future `log_donation`), I’d standardize on this shape:

```python
# app/slices/finance/services.py

from app.extensions import db, event_bus
from app.lib.chrono import now_iso8601_ms
from app.slices.finance.models import Fund, Journal, JournalLine, Period, BalanceMonthly

def log_expense(
    *,
    fund_ulid: str,
    project_ulid: str,
    amount_cents: int,
    occurred_on: str,
    category: str,
    vendor: str,
    request_id: str,
    actor_ulid: str | None,
    dry_run: bool = False,
) -> ExpenseDTO:
    # 1) Basic semantics
    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0")

    fund = db.session.get(Fund, fund_ulid)
    if not fund:
        raise LookupError(f"unknown fund_ulid {fund_ulid}")

    # 2) Period handling (reuse _period_key_from/_ensure_open_period)
    period_key = _period_key_from(occurred_on)
    _ensure_open_period(period_key)

    memo = f"{category} — {vendor}" if vendor else category

    if dry_run:
        return ExpenseDTO(
            id="DRY-RUN",
            fund_id=fund.ulid,
            project_id=project_ulid,
            occurred_on=occurred_on,
            vendor=vendor,
            amount_cents=amount_cents,
            category=category,
            approved_by_ulid=None,
            flags=["dry_run"],
        )

    # 3) Build balanced journal lines
    lines = [
        { ... },  # DR expense
        { ... },  # CR cash/bank
    ]

    journal_ulid = post_journal(
        source="calendar",
        external_ref_ulid=project_ulid,
        happened_at_utc=occurred_on,
        currency="USD",
        memo=memo,
        lines=lines,
        created_by_actor=actor_ulid,
    )

    # 4) Return DTO
    return ExpenseDTO(
        id=journal_ulid,
        fund_id=fund.ulid,
        project_id=project_ulid,
        occurred_on=occurred_on,
        vendor=vendor,
        amount_cents=amount_cents,
        category=category,
        approved_by_ulid=None,
        flags=[],
    )
```

Pieces to notice (these are the “Service Lego studs”):

- **Inputs are typed keyword-only args** (matching the contract).

- Uses existing helpers (`_period_key_from`, `_ensure_open_period`, `post_journal`).

- Raises **ValueError / LookupError** when something’s wrong.

- Does **one** `event_bus.emit` via `post_journal` (which already emits `journal.posted`).

- Returns a DTO at the end; no ContractError here.

That’s the exact same shape you can use for `log_donation`, `record_inkind`, etc.

---

### 2.5 Event Lego

You’ve already standardized this across the app by routing everything through `app/extensions/event_bus.emit(...)`.

So the **Event Lego** is simply:

```python
event_bus.emit(
    domain="finance",
    operation="journal.posted",
    request_id=request_id,
    actor_ulid=actor_ulid,
    target_ulid=journal_ulid,
    refs={...},
    changed=None,
    meta=None,
    happened_at_utc=j.posted_at_utc,
    chain_key="finance.journal",
)
```

And for Finance, you already do that inside `post_journal`.

---

### 2.6 Policy Lego

As you said, the Policy Lego is already pretty clean:

- **Single entrypoint** `app/extensions/policies.py` for loading + validating JSON policy files.

- Mapping of `policy_*.json` → `policy_*.schema.json` is centralized there.

So Finance services that need fund archetypes, journal flags, or budget caps will:

- Call `policy_semantics` helpers (which themselves call `policies.load_policy_*`).

- Never open JSON files directly.

That pipeline is already in good shape; we’re just going to *use* it more.

---

## 3. Applying this to Finance v2 right now

Here’s how I’d sequence the Finance refactor around these Legos:

### Step 1 — Add helpers to `finance_v2.py`

- Copy `_as_contract_error`, `_require_str`, `_require_ulid`, `_require_int_ge` from `sponsors_v2` into `finance_v2`.

- Optionally add `_require_iso_date` if you want a date sanity check.

Now every Finance contract can do the same “try / except / raise _as_contract_error(...)” dance as Sponsors.

### Step 2 — Convert Finance contracts to typed args

For each function in `finance_v2` that currently takes `payload: dict` (e.g. `log_expense`, `record_receipt`, `create_fund`, `set_budget`, etc.), turn it into:

- **Keyword-only typed args**.

- **Shape check** with `_require_*`.

- **Delegation** to `app.slices.finance.services` with typed args.

- **Exception wrapping** into `ContractError`.

Example target for `log_expense` (rough sketch):

```python
def log_expense(
    *,
    fund_ulid: str,
    project_ulid: str,
    amount_cents: int,
    occurred_on: str,
    category: str,
    vendor: str | None = None,
    request_id: str | None = None,
    actor_ulid: str | None = None,
    dry_run: bool = False,
) -> ExpenseDTO:
    where = "finance_v2.log_expense"
    try:
        fund_ulid = _require_ulid("fund_ulid", fund_ulid)
        project_ulid = _require_ulid("project_ulid", project_ulid)
        amount_cents = _require_int_ge("amount_cents", amount_cents, minval=1)
        category = _require_str("category", category)

        # request_id handling same as Sponsors
        ...
        return svc.log_expense(
            fund_ulid=fund_ulid,
            project_ulid=project_ulid,
            amount_cents=amount_cents,
            occurred_on=occurred_on,
            category=category,
            vendor=vendor or "",
            request_id=request_id,
            actor_ulid=actor_ulid,
            dry_run=dry_run,
        )
    except Exception as exc:
        raise _as_contract_error(where, exc)
```

### Step 3 — Adjust Finance services to accept typed args

For each service currently taking `payload: dict` (like `log_expense(payload: dict, ...)`), gradually refactor to the **Service Lego** above:

- Signature with keyword-only typed args.

- Use helpers like `_period_key_from` and `_ensure_open_period`.

- Raise `ValueError` / `LookupError` / `PermissionError` when things are wrong.

- Build and call `post_journal` (which already validates, updates balances, and emits ledger events).

- Return the appropriate DTO.

You don’t have to do them all at once—you can start with `log_expense` and the soon-to-exist `log_donation`, then work outward.

---

## 4. Where this leaves us

After this refactor, your “industrial Lego” story looks like:

- **DTO Lego**: `@dataclass` shapes per pipeline (already in Finance).

- **Service Error Lego**: services raise Python built-ins + small slice-specific errors; no ContractError here.

- **Service Lego**: typed keyword-only args, call models + helpers, call `event_bus.emit` (indirectly via core helpers), return DTOs.

- **Contract Lego**: typed args, `_require_*` shape checks, call service, wrap any exception with `_as_contract_error` → `ContractError`.

- **Event Lego**: everything goes through `event_bus.emit` with the same signature (already canon).

- **Policy Lego**: only `policies.py` + `policy_semantics` touch governance JSON.

Finance slice then becomes the **canonical** example of these patterns, which you can point future devs at and say: “Copy this shape, don’t invent new ones.”

---

If you’d like, next pass we can:

- Take **one live function** (e.g. `log_expense`) and I’ll give you a literal before/after diff that converts it to these legos, so you have a concrete template to apply to `log_donation`, `record_receipt`, etc.
