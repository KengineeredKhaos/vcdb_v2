# Admin Intervention Canon

## Core statement

Admin is a **cue, triage, and launch** surface.  
Admin is **not** the owner of slice truth, business mutation, repair logic, or terminal business outcome.

When a slice requires Admin intervention, the owning slice must:

1. raise or refresh an `admin_alert`,
2. provide a real slice-local Admin issue surface,
3. perform the actual review, approval, rejection, repair, or corrective action inside the owning slice,
4. record its own truth and audit trail inside the owning slice,
5. close the `admin_alert` when the slice reaches terminal state.

**Admin Inbox must remain a truthful reflection of slice-owned intervention state, not a second source of workflow truth.**

## Canon sentence

**Admin owns visibility, queue posture, and launch.**  
**The owning slice owns truth, mutation, audit, and completion.**

### Ghosts of apps-past warning

This design exists to prevent the return of parallel inboxes, half-owned review flows, and legacy naming drift.

Do not reintroduce older nouns or half-replacements such as:

- inbox item
- review request
- issue kind
- `source_ref_ulid`
- `subject_ref_ulid`
- `resolution_route`
- `severity`

Those names belonged to earlier transitional designs. Reintroducing them creates translation glue, duplicate concepts, and maintenance confusion.

Use the canon nouns:

- `admin_alert`
- `request_id`
- `target_ulid`
- `reason_code`
- `resolution_target`
- `<Slice>AdminIssue`
- `admin_issue_routes.py`
- `admin_issue_services.py`

### Why this pattern exists

This pattern is intentionally repetitive.

That repetition is not accidental. It is how the application prevents Admin from becoming a second business engine and prevents slices from smuggling workflow truth into the Admin overlay.

Uniform naming and repeated file, module, and table shapes are used here to reduce guesswork, reduce hidden exceptions, and make future slice implementations predictable.

### Do not do these things

Do not store slice business truth only in `admin_alert`.

Do not let Admin routes mutate foreign-slice truth directly.

Do not dedupe alerts on `target_ulid` alone.

Do not store plain-string route targets when a structured `resolution_target` is expected.

Do not invent slice-local synonyms for canon nouns unless the canon is formally revised.

Do not rebuild `review_kind` under a new alias when `reason_code` is the canon term.

Do not create “temporary” compatibility names unless they are scheduled for removal.

Do not let an unresolved migration leave both old and new concepts alive at once.

### When in doubt

When adding a new Admin intervention flow, ask these questions in order:

1. What is the owning slice?
2. What is the slice-local `reason_code`?
3. What is the `request_id` for this logical operation?
4. What is the `target_ulid`, if any?
5. What slice-local `<Slice>AdminIssue` row records the issue?
6. What real GET surface will Admin launch into?
7. What slice-local service performs the real mutation or repair?
8. How does the owning slice close the `admin_alert` honestly?

If any answer is vague, the flow is not ready for implementation.

### Migration caution

During migration, do not leave both the retired review-request pattern and the new Admin-issue pattern active in parallel longer than necessary.

A half-migrated system is worse than either old or new in isolation because it produces duplicate concepts, duplicate queries, duplicate routes, and misleading history.

Retire old names completely once the new pattern is adopted.

Do not keep compatibility wrappers longer than one migration cycle unless they are explicitly documented and tracked for removal.

### Boring is good here

This is not a place for clever abstractions.

A Future Dev should be able to open any slice and find the same:

- table shape
- file names
- service seams
- route posture
- Admin closure pattern
- naming conventions

Predictability is the feature.

### `details_json` caution

`details_json` exists to reduce needless schema churn for slice-local, non-PII intervention facts.

It is not permission to dump arbitrary business truth, PII, or narrative history into a generic JSON hole.

If a fact becomes central to slice logic, querying, validation, or reporting, it may deserve a real column or a dedicated slice-local table later.

### Slice-local vocabulary rule

Each slice owns its own `reason_code` values, but that freedom is bounded.

All `reason_code` values must:

- begin with `advisory_`, `anomaly_`, or `failed_`
- include the slice name
- describe one stable intervention type
- remain durable enough for reporting and triage

Do not use informal prose, temporary wording, or user-facing sentence fragments as `reason_code` values.

### Note to future maintainers, including the original author

If you have forgotten why this structure seems repetitive, that is normal. Read the ownership rule first.

If a proposed shortcut would make Admin own more truth, more mutation, or more repair logic, it is probably the wrong shortcut.

---

## Vocabulary freeze

### Admin overlay nouns

Use these nouns everywhere in the Admin slice and in cross-slice DTOs:

- `admin_alert` = canonical Admin queue storage
- **Admin Inbox** = operator-facing UI view over `admin_alert`
- `request_id` = cradle-to-grave collation key for the logical operation
- `target_ulid` = business object or primary target of the intervention
- `reason_code` = machine classification of the Admin intervention
- `resolution_target` = structured route target for launching into the owning slice

Do **not** introduce parallel nouns such as:

- inbox item
- review message
- admin notification
- generic queue message
- `source_ref_ulid`
- `subject_ref_ulid`
- `issue_kind`

Those were transitional names. The canon nouns are now:

- `request_id`
- `target_ulid`
- `reason_code`

### Slice-local nouns

For slice-local persistence and mechanics, use:

- `<Slice>AdminIssue`
- `admin_issue_routes.py`
- `admin_issue_services.py`

Do **not** use:

- `<Slice>AdminReviewRequest`
- `admin_review_routes.py`
- `admin_review_services.py`

unless grandfathered temporarily during migration.

---

## Ownership rule

Admin owns:

- visibility
- queueing
- operator triage posture
- acknowledgement / snooze / duplicate / dismiss
- launch into owning slice

The owning slice owns:

- validation
- business rules
- state mutation
- local persistence
- repair mechanics
- slice-owned audit and ledger emission
- terminal completion
- closure signal back to Admin

No slice may outsource its business mutation to Admin.

No Admin route may become a second business workflow engine.

No Admin service may perform cross-slice repair hacks, shortcut business mutation, or become a shadow repair layer.

---

## Queue-family canon

Every `reason_code` must begin with one of these families:

- `advisory_`
- `anomaly_`
- `failed_`

### Meaning

`advisory_*`  
: human attention, decision, review, or business intervention required

`anomaly_*`  
: slice-local inconsistency, drift, or corrective inspection/repair required

`failed_*`  
: job, cron, compile, archive, validation, or other process failure requiring Admin awareness

This family prefix replaces the need for a separate `severity` field in the first real queue design.

Do **not** store `severity` on `admin_alert` or `<slice>_admin_issue` unless canonized later by a demonstrated need.

---

## Reason-code naming canon

Each slice owns its own `reason_code` vocabulary inside its own `admin_issue_services.py`.

Pattern:

- `advisory_<slice>_<operation>`
- `anomaly_<slice>_<operation>`
- `failed_<slice>_<operation>`

Examples:

- `advisory_resources_onboard`
- `advisory_customers_referral_exception`
- `advisory_sponsors_grant_acceptance`
- `anomaly_ledger_projection_drift`
- `anomaly_logistics_inventory_reconcile`
- `failed_governance_policy_compile`
- `failed_admin_archive_sweep`

### Naming rules

Keep `reason_code`:

- machine-readable
- stable over time
- short enough for filters and indexes
- descriptive enough for triage/reporting
- slice-owned, not globally micromanaged

Do **not** use vague labels like:

- `needs_attention`
- `problem`
- `warning`
- `review_required`

The family prefix already tells you the broad class. The tail should tell you the slice-specific meaning.

---

## Admin alert overlay canon

`admin_alert` is the single canonical Admin queue record.

Admin Inbox is only the UI view over `admin_alert`, not a separate persistence concept.

`admin_alert` rows must remain PII-free.

Allowed in `admin_alert`:

- `request_id`
- `target_ulid`
- `source_slice`
- `reason_code`
- `source_status`
- `admin_status`
- `title`
- `summary`
- `workflow_key`
- `resolution_target_json`
- non-PII `context_json`
- triage timestamps / actor references

Not allowed in `admin_alert`:

- names
- addresses
- phone numbers
- emails
- DOB
- notes text
- detailed history blobs
- other protected or slice-private narrative content

If an operator needs richer facts, Admin launches into the owning slice.

---

## Dedupe canon

Dedupe must be request-first, not business-object-first.

At most one **open** `admin_alert` may exist for the tuple:

- `source_slice`
- `reason_code`
- `request_id`
- `target_ulid`

This allows:

- same `source_slice`
- same `reason_code`
- same `target_ulid`
- different `request_id`

to coexist as distinct Admin alerts when they represent distinct logical operations.

`target_ulid` is for grouping, reporting, and cross-alert visibility.  
It is **not** the primary dedupe key by itself.

---

## Status canon

Keep `source_status` and `admin_status` separate.

### `source_status`

Owned by the slice.  
Examples:

- `pending_review`
- `approved`
- `rejected`
- `cancelled`
- `needs_repair`
- `repair_complete`
- `failed`
- `superseded`

### `admin_status`

Owned by Admin. Use only:

- `open`
- `acknowledged`
- `in_review`
- `snoozed`
- `resolved`
- `source_closed`
- `dismissed`
- `duplicate`

Rule:

- `resolved` and `source_closed` are normally slice-driven outcomes
- `dismissed` and `duplicate` are Admin triage outcomes

`close_*_admin_issue()` should normally close Admin with `admin_status="resolved"`.

If the slice truth changes elsewhere and the Admin cue is no longer actionable, the owning slice should close the alert with `admin_status="source_closed"`.

---

## Resolution-target canon

The launch target must be a real slice entry surface and must resolve to the owning slice’s **GET** Admin issue surface, not directly to a mutating action.

Use a structured route target:

```python
from dataclasses import dataclass
from typing import Mapping

@dataclass(frozen=True)
class AdminResolutionTargetDTO:
    route_name: str
    route_params: Mapping[str, str]
    launch_label: str
    http_method: str = "GET"
```

Do **not** store only a plain URL string if you can avoid it.  
A structured route target is easier to validate, easier to test, and less fragile during refactors.

Do **not** point the resolution target directly at approve/reject/repair POST routes.

---

## Slice-local Admin issue model template

Each slice that needs Admin intervention should repeat the following documented model-class schema pattern, with slice-local table name and class name substituted.

This template should be repeated per slice in `models.py`.  
It is a documented pattern, not a lib-core abstract mixin.

```python
class <Slice>AdminIssue(db.Model, ULIDPK, IsoTimestamps):
    __tablename__ = "<slice>_admin_issue"

    request_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    target_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True, index=True
    )

    reason_code: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    source_status: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )

    requested_by_actor_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )
    resolved_by_actor_ulid: Mapped[str | None] = mapped_column(
        String(26), nullable=True
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    details_json: Mapped[dict[str, object] | None] = mapped_column(
        db.JSON, nullable=True
    )

    closed_at_utc: Mapped[str | None] = mapped_column(
        String(30), nullable=True, index=True
    )

    __table_args__ = (
        db.Index(
            "ix_<slice>_admin_issue_active",
            "reason_code",
            "source_status",
            "closed_at_utc",
        ),
        db.Index(
            "ix_<slice>_admin_issue_request_reason",
            "request_id",
            "reason_code",
        ),
        db.Index(
            "ix_<slice>_admin_issue_target_reason",
            "target_ulid",
            "reason_code",
        ),
    )
```

### Template rules

- Use `ULIDPK` and `IsoTimestamps` for uniform IDs and timestamps across slice models.
- `request_id` is the logical collation key.
- `target_ulid` is the business target when one exists.
- `reason_code` replaces `review_kind`.
- `details_json` exists to reduce future migrations for slice-specific, non-PII intervention facts.
- `closed_at_utc` remains explicit because terminal closure is business truth distinct from row creation/update.

### Migration rule

Burn down existing `<Slice>AdminReviewRequest` tables and replace them with `<Slice>AdminIssue` tables rather than carrying narrow review-centric naming forward.

---

## File and module canon

Each slice that supports Admin intervention must keep its mechanics in dedicated files:

```text
app/
  slices/
    <slice>/
      admin_issue_routes.py
      admin_issue_services.py
      mapper.py
      models.py
```

### Responsibility split

`models.py`  
: slice-local persistence, including `<Slice>AdminIssue` when needed

`admin_issue_routes.py`  
: thin entry points only; GET detail/review surfaces and POST decision/repair actions; auth/RBAC at the route edge; commit/rollback at the route edge

`admin_issue_services.py`  
: all slice-local Admin intervention mechanics; create/refresh issue rows; validate actionable state; perform slice-owned mutation or repair; emit slice-owned audit/ledger events; close Admin alert

`mapper.py`  
: DTO assembly and view shaping only; no mutation, no closure, no ledger emission

The current Resources `admin_issue_routes.py`, `admin_issue_services.py`, and workflow handoff seam in `onboard_services.py` demonstrate the reference mechanical split: workflow route to workflow-service handoff, slice-local issue creation, `admin_v2` alert upsert, owning-slice GET issue surface, owning-slice POST resolution, and slice-owned terminal closure.

---

## What triggers an `admin_alert`?

`admin_alert` mechanics are standardized across slices, but the decision to raise an alert is governed by slice-owned business truth.

> The **mechanics** are uniform. The **trigger semantics** are slice-owned.

Common trigger classes include:

- **Operator-driven completion cue**  
  **Customers**: An operator completes the workflow, and advisory Admin cues may be raised afterward. In this slice, `completion` is operator-driven because immediate needs may require immediate action. Admin follow-up must not block or unwind that completion.

- **Business-flow gating cue**  
  **Resources / Sponsors**: The normal workflow reaches a point where Admin, Governance, or Board review is required before the matter should be considered fully cleared. In these slices, `admin_alert` creation is part of the ordinary business flow because onboarding, approval, or organizational vetting may require ethical, policy, or governance review.

- **Programmatic diagnostic cue**  
  **Ledger / Finance / Governance**: A system-driven check detects drift, anomaly, failure, or integrity risk and raises Admin attention automatically. In these slices, `admin_alert` creation will often be programmatically driven by diagnostics, validation sweeps, integrity checks, archival checks, or scheduled monitoring.

---

## Reference implementation flow — Resources onboarding

Resources is the proving-ground implementation for slice-local Admin issue mechanics.

The established flow is:

1. `resources/__init__.py` registers both `onboard_routes` and `admin_issue_routes` so the slice exposes both the operator wizard and the Admin issue surface.

2. The wizard completion route in `onboard_routes.py` handles nonce validation, request ID creation, and actor lookup at the route edge, then calls `submit_onboard_admin_issue(...)`.

3. `submit_onboard_admin_issue(...)` in `onboard_services.py` is the wizard-side handoff seam. It marks the onboarding wizard step as `complete`, then locally imports and calls `raise_onboard_admin_issue(...)`.

4. `raise_onboard_admin_issue(...)` in `admin_issue_services.py` creates or reuses the slice-local `ResourceAdminIssue` row and then upserts `admin_alert` through `admin_v2` using `AdminAlertUpsertDTO` and `AdminResolutionTargetDTO`.

5. Admin launches into the owning slice through the GET surface in `admin_issue_routes.py`, not directly into a mutating action.

6. `resolve_onboard_admin_issue(...)` performs the real Resources-side approval or rejection, updates slice truth, terminalizes the slice-local issue, closes the `admin_alert`, and emits slice-owned event data.

This is the blueprint. Future slices should copy this flow with slice-local names and slice-local business logic, not invent new mechanics.

### Resources flow summary

wizard route  
→ `submit_<operation>_admin_issue()` handoff seam  
→ `raise_<operation>_admin_issue()`  
→ create or refresh `<Slice>AdminIssue`  
→ `admin_v2.upsert_alert()`  
→ Admin Inbox launch  
→ owning-slice GET issue surface  
→ owning-slice POST resolution  
→ terminalize `<Slice>AdminIssue`  
→ `admin_v2.close_alert()`  
→ slice-owned audit / event trail

---

## Required service pattern

For each slice-specific operation, define four seams with a short, boring, slice-local operation stem.

Pattern:

- `raise_<operation>_admin_issue()`
- `<operation>_issue_get()`
- `resolve_<operation>_admin_issue()`
- `close_<operation>_admin_issue()`

Examples:

- `raise_onboard_admin_issue()`

- `onboard_issue_get()`

- `resolve_onboard_admin_issue()`

- `close_onboard_admin_issue()`

- `raise_referral_exception_admin_issue()`

- `referral_exception_issue_get()`

- `resolve_referral_exception_admin_issue()`

- `close_referral_exception_admin_issue()`

- `raise_projection_drift_admin_issue()`

- `projection_drift_issue_get()`

- `resolve_projection_drift_admin_issue()`

- `close_projection_drift_admin_issue()`

### Responsibility canon

`raise_<operation>_admin_issue()`  
: create or refresh the slice-local `<Slice>AdminIssue` row, then upsert the `admin_alert`

`<operation>_issue_get()`  
: read-only page/data loader for the owning slice’s Admin intervention surface

`resolve_<operation>_admin_issue()`  
: perform the real slice-local business action or repair, update slice truth, emit slice-owned audit/ledger events, terminalize the slice-local issue, then close the Admin alert

`close_<operation>_admin_issue()`  
: slice-local bridge back to `admin_v2` to mark the Admin alert terminal

### Idempotency rule

Raise and close seams must be safe to call more than once for the same logical issue.

### Stale-action rule

`resolve_<operation>_admin_issue()` must verify that the issue is still actionable at the time of mutation. If already terminal, superseded, cancelled, or otherwise no longer actionable, it must refuse mutation and return the appropriate terminal outcome.

---

## Representative skeleton snippets

These are deliberately small, boring, and repeatable.  
They are not meant to be clever. They are meant to be copied safely.

### 1. Slice route registration

For slices that expose both a workflow surface and an Admin issue surface, register both route modules in the slice package.

```python
# app/slices/<slice>/__init__.py
from __future__ import annotations

from . import (
    admin_issue_routes,  # noqa: F401
    <workflow>_routes,   # noqa: F401
)
from .routes import bp

__all__ = ["bp"]
```

### 2. Workflow route handoff to Admin issue

The workflow route owns request/nonce/form handling and transaction boundaries.  
It does not own Admin issue lifecycle mechanics.

```python
# app/slices/<slice>/<workflow>_routes.py
@bp.route("/<workflow>/<target_ulid>/complete", methods=["GET", "POST"])
@login_required
def <workflow>_complete(target_ulid: str):
    req = ensure_request_id()
    actor = get_actor_ulid()

    if request.method == "GET":
        return render_template(...)

    # validate nonce / submitted form state here

    try:
        <workflow>_svc.submit_<operation>_admin_issue(
            target_ulid=target_ulid,
            request_id=req,
            actor_ulid=actor,
        )
        db.session.commit()
        flash("Submitted for Admin approval.", "success")
        return redirect(...)
    except Exception:
        db.session.rollback()
        raise
```

### 3. Workflow-service handoff seam

This seam belongs in the slice workflow service module.  
It completes workflow progression, then hands off to the slice-local Admin issue service.

Keep the import local when that avoids circular-import problems.

```python
def submit_<operation>_admin_issue(
    *,
    target_ulid: str,
    request_id: str,
    actor_ulid: str | None,
):
    """
    Complete workflow progression and hand off to the slice-local
    Admin issue flow.
    """
    from .admin_issue_services import raise_<operation>_admin_issue

    mark_step(
        target_ulid=target_ulid,
        step="complete",
        request_id=request_id,
        actor_ulid=actor_ulid,
    )

    return raise_<operation>_admin_issue(
        target_ulid=target_ulid,
        actor_ulid=actor_ulid,
        request_id=request_id,
    )
```

### 4. Raise seam in `admin_issue_services.py`

This seam creates or refreshes the slice-local `<Slice>AdminIssue` row, then upserts `admin_alert` through `admin_v2`.

```python
def raise_<operation>_admin_issue(
    *,
    target_ulid: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> AdminAlertReceiptDTO:
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)

    issue = _get_open_issue(
        request_id=rid,
        target_ulid=target_ulid,
        reason_code=REASON_CODE_<OPERATION>,
    )
    if issue is None:
        issue = _create_<operation>_issue(
            target_ulid=target_ulid,
            actor_ulid=act,
            request_id=rid,
        )

    return upsert_alert(
        AdminAlertUpsertDTO(
            source_slice="<slice>",
            reason_code=issue.reason_code,
            request_id=str(issue.request_id),
            target_ulid=issue.target_ulid,
            title=issue.title,
            summary=issue.summary,
            source_status=issue.source_status,
            workflow_key="<slice>_<operation>_issue",
            resolution_target=AdminResolutionTargetDTO(
                route_name="<slice>.admin_issue_<operation>_get",
                route_params={"issue_ulid": issue.ulid},
                launch_label="Open <slice> <operation> issue",
            ),
            context=_build_<operation>_issue_context(target_ulid),
        )
    )
```

### 5. GET issue surface in `admin_issue_routes.py`

The GET surface is the only launch target Admin should use.

```python
@bp.get("/admin-issue/<issue_ulid>", endpoint="admin_issue_<operation>_get")
@login_required
@roles_required("admin")
def admin_issue_<operation>_get(issue_ulid: str):
    page = issue_svc.<operation>_issue_get(issue_ulid)
    if (request.args.get("format") or "").strip().lower() == "json":
        return {"ok": True, "data": page}, 200
    return render_template("<slice>/admin_issue_<operation>.html", page=page)
```

### 6. POST resolution route

The POST route owns request ID generation and transaction boundaries.  
The service owns the business mutation.

```python
@bp.post(
    "/admin-issue/<issue_ulid>/approve",
    endpoint="admin_issue_<operation>_approve",
)
@login_required
@roles_required("admin")
def admin_issue_<operation>_approve(issue_ulid: str):
    req = ensure_request_id()
    actor = auth_ctx.current_actor_ulid()

    try:
        issue_svc.resolve_<operation>_admin_issue(
            issue_ulid=issue_ulid,
            decision="approve",
            actor_ulid=actor,
            request_id=req,
        )
        db.session.commit()
        flash("Approved.", "success")
    except Exception:
        db.session.rollback()
        raise

    return redirect(url_for("admin.inbox"))
```

### 7. Resolution service seam

This seam performs the real slice-owned action, terminalizes the issue, closes the Admin alert, and emits slice-owned event data.

```python
def resolve_<operation>_admin_issue(
    *,
    issue_ulid: str,
    decision: str,
    actor_ulid: str | None,
    request_id: str | None,
) -> AdminAlertReceiptDTO | None:
    rid = ensure_request_id(request_id)
    act = ensure_actor_ulid(actor_ulid)

    issue = _get_issue_or_raise(issue_ulid)

    if issue.closed_at_utc:
        return close_<operation>_admin_issue(
            issue_ulid=issue.ulid,
            source_status=issue.source_status,
            close_reason="already_terminal",
            admin_status="source_closed",
        )

    # perform real slice-local mutation here

    _mark_issue_terminal(
        issue_ulid=issue.ulid,
        source_status="<terminal_source_status>",
        actor_ulid=act,
        request_id=rid,
    )

    receipt = close_<operation>_admin_issue(
        issue_ulid=issue.ulid,
        source_status="<terminal_source_status>",
        close_reason="<slice_specific_reason>",
        admin_status="resolved",
    )

    # emit slice-owned event / audit here

    return receipt
```

### 8. Close seam back to Admin

The owning slice closes the Admin alert using the same `request_id`, `target_ulid`, and `reason_code` truth carried by the slice-local issue.

```python
def close_<operation>_admin_issue(
    *,
    issue_ulid: str,
    source_status: str,
    close_reason: str,
    admin_status: str = "resolved",
) -> AdminAlertReceiptDTO | None:
    issue = _get_issue_or_raise(issue_ulid)

    return close_alert(
        AdminAlertCloseDTO(
            source_slice="<slice>",
            reason_code=issue.reason_code,
            request_id=issue.request_id,
            target_ulid=issue.target_ulid,
            source_status=source_status,
            close_reason=close_reason,
            admin_status=admin_status,
        )
    )
```

### 9. Route-access test skeleton

Every new Admin issue surface should have access tests proving the public route posture.

```python
def test_<slice>_admin_issue_requires_admin_for_anonymous(client):
    resp = client.post("/<slice>/admin-issue/<fake_ulid>/approve")
    assert_unauthenticated(resp)


def test_<slice>_admin_issue_denies_non_admin_users(client, ...):
    login_and_settle_password(...)
    resp = client.post("/<slice>/admin-issue/<fake_ulid>/approve")
    assert_forbidden(resp)
```

### Snippet rule

These snippets are intentionally repetitive.  
Future maintainers should prefer copying and adapting them over inventing new Admin issue mechanics.

---

## Route-shape canon

`admin_issue_routes.py` should follow this shape:

- one GET route for the slice-local issue surface
- one or more POST routes for explicit terminal actions
- `login_required` and RBAC at the route edge
- `ensure_request_id()` at the route edge for mutating actions
- route owns commit/rollback
- service owns mutation logic
- redirect back to Admin Inbox or the slice detail surface after commit

The current Resources route file is the pattern being generalized: GET loads page data; POST calls the service with `decision` and `request_id`; route commits or rolls back.

---

## Service-shape canon

`admin_issue_services.py` should follow this shape:

- validate actor/request guards
- create or fetch the slice-local `<Slice>AdminIssue`
- build non-PII Admin context payload
- upsert `admin_alert`
- load current slice truth
- apply approval/rejection/repair inside the slice
- mark slice-local issue terminal
- close Admin alert
- emit slice-owned event/ledger facts using `request_id` and `target_ulid`

The current Resources services files already demonstrate the intended ownership split: workflow progression remains in the workflow service, while `admin_issue_services.py` owns slice-local issue lifecycle, Admin alert raise/close seams, and slice-owned resolution behavior.

---

## Workflow-key canon

Each Admin flow should also define a stable `workflow_key` for grouping and reporting.

Examples:

- `resources_onboard_issue`
- `customers_referral_exception_issue`
- `sponsors_grant_acceptance_issue`
- `ledger_projection_drift_issue`

`workflow_key` should stay stable even if route names later change.

---

## Structural truth rule

A route cannot be called secure or hardened until it is:

- registered
- reachable
- internally wired
- capable of executing its owning-slice Admin issue path
- capable of closing the Admin alert honestly

Until then, it is **UNTERMINATED**.

---

## Final freeze

**`admin_alert` is the single canonical Admin queue record.**  
**Admin Inbox is the UI view over `admin_alert`, not a separate workflow system.**  
**Each slice may repeat a documented `<Slice>AdminIssue` model template in its own `models.py`.**  
**Each slice owns its own `reason_code` vocabulary inside `admin_issue_services.py`.**  
**`reason_code` families are `advisory_*`, `anomaly_*`, and `failed_*`.**  
**`request_id` and `target_ulid` are the cross-slice collation nouns.**  
**Routes stay thin, services own mutation, and Admin never becomes the repair engine.**

---

## Testing Regime

Existing Admin Inbox tests are workflow tests, not just route smoke tests.  
They exist to prove queue posture, owning-slice launch, and non-mutation of foreign slice truth. Added slice functionality should be exercised  in the test regime as well before publishing.



---

## Finance addendum — Admin intervention posture

Finance confirms the Admin Intervention pattern, but with one additional caution:
Finance is a behind-the-curtain integrity slice whose failures may affect whether
staff-facing money posture can be trusted at all.

### Ownership rule in Finance

Admin still owns:

- visibility
- queue posture
- launch
- operator triage

Finance still owns:

- detection
- integrity truth
- quarantine truth
- repair logic
- manual-resolution classification
- terminal closure
- audit / ledger consequences

Admin must not become a second accounting engine, a second posting surface, or a
shadow repair layer for Finance.

### Finance issue posture canon

Finance Admin issue surfaces should answer four plain questions before showing
raw evidence:

- What is the current posture?
- What is the recommended next step?
- Is a deterministic repair available?
- What scope is affected?

These answers should be understandable without color and without requiring the
operator to decode JSON evidence first.

### Quarantine canon in Finance

Finance uses quarantine as the active safety fence and FinanceAdminIssue as the
case/evidence file.

Those are separate truths:

- `FinanceAdminIssue` = the case, evidence, review state, and operator path
- `FinanceQuarantine` = the active safety block preventing unsafe downstream use

Do not collapse quarantine truth into the issue row, and do not treat the issue
row alone as the active safety fence.

### Scope canon in Finance

Finance must narrow quarantine scope whenever it can prove the narrower blast
radius honestly.

Preferred posture:

- funding demand scope when provable
- project scope when provable
- journal / semantic posting / ops-float scope when provable
- global scope only when Finance cannot honestly prove narrower safety

Global quarantine should be rare.

But when an active global Finance quarantine exists, it is absolute for the
staff Go/NoGo seam.

If any active global Finance quarantine exists, Finance must return:

- `no_go`
- `escalate_to_admin = true`
- a short plain message directing staff to contact Admin

There is no staff override path for an active global Finance quarantine.

### Repair canon in Finance

Finance may auto-repair only truths that are rebuildable or deterministically
derivable from more authoritative Finance truth.

Examples of acceptable repair classes:

- projection rebuild from authoritative journal truth
- semantic posting fact correction from clean journal truth

Finance must not silently rewrite authoritative journal truth in the name of
Admin convenience.

If journal truth is wrong, the Finance/Admin surface should classify, fence,
document, and route the operator toward the appropriate manual accounting or
future reversal/adjustment path rather than pretending to auto-fix it.

### Operator note canon in Finance

Finance issue notes should remain terse and operational.

Use a short operator note only for current-status truth such as:

- who was contacted
- callback / handoff clue
- expected next touch
- current blocked / waiting posture

Do not turn issue notes into narrative history blobs.

### Staff-facing seam canon

Staff does not need Finance internals.

For staff-facing demand processing, Finance should expose only a trusted
Go/NoGo-style seam:

- safe to proceed now, or
- blocked; contact Admin

Admin/Auditor drill-down remains rich.
Staff-facing Finance truth remains blunt, minimal, and trustworthy.

### Reuse warning for future slices

Finance demonstrates that some slices need both:

- deterministic self-healing for derived truth, and
- containment / escalation workflows for authoritative truth

Future behind-the-curtain slices, especially Ledger, should copy the ownership
pattern and safety posture, not merely the screen layout.
