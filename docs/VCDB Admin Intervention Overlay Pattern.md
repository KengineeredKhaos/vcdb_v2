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

**Admin owns visibility, queue posture, and launch.  
The owning slice owns truth, mutation, audit, and completion.**

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

The launch target must be a real slice entry surface and must resolve to the owning slice’s **GET** Admin issue surface, not directly to a mutating action. This preserves the current boundary and review-entry rule from the earlier canon.

Use a structured route target:

```python
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

Burn down existing `<Slice>AdminReviewRequest` tables and replace them with `<Slice>AdminIssue` tables rather than carrying narrow review-centric naming forward. The current Resources table is the example of what is being retired.

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

The current Resources `admin_review_routes.py` and `admin_review_services.py` demonstrate the mechanical split being preserved, even though the names are about to change. Routes are thin, services do the work, and the service emits the slice-owned event after resolution.

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

The current Resources services file already demonstrates the intended service ownership: create local review record, upsert Admin item, load facts, resolve in-slice, close the Admin item, and emit slice-owned event bus data. This revision keeps that ownership split while renaming the nouns and broadening beyond review-only flows.

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
