# Resources MOU impact-review rubric

**This topic is deferred for post-MVP design and implementation.**

**SLA review asks whether the application can support, track, and enforce the agreement’s operational service commitments.**

**MOU review asks whether the application can support the agreement’s structural and policy implications.**

## Canon sentence for this operation

**Resource MOU review is an Admin intervention workflow to certify that all application-specific impacts of the agreement have been documented, addressed, tested, and activated; it is not a general approval of the relationship itself.**

## What this operation is

**MOU review is an application-impact intervention workflow.**

It is **not** general partner approval.  
It is a Resources-owned review that asks:

**Have all application-specific impacts of this MOU been documented, addressed, tested, and activated so the agreement can be honored safely in the app?**

Approval means “system-ready for this MOU’s effects.”  
Rejection means “this MOU’s app impact is a deal-breaker or out of scope.”

## Operation stem

Use:

- `raise_mou_admin_issue()`

- `mou_review_get()`

- `resolve_mou_admin_issue()`

- `close_mou_admin_issue()`

That matches the frozen naming canon.

## Machine keys

Freeze these now:

- `issue_kind = "mou_impact_review_required"`

- `workflow_key = "resource_mou_impact_review"`

And per your canon:

- `source_ref_ulid` = Resources slice-owned review request ULID

- `subject_ref_ulid` = Resource business object ULID

## Source-status meanings

Keep Resources source status boring:

- `pending_review`

- `approved`

- `rejected`

- `cancelled`

Admin queue status stays separate and uses the shared Admin meanings like `open`, `resolved`, and `source_closed`.

## What should raise this issue

Raise an MOU review request when an existing Resource relationship gains or updates an MOU whose terms may affect:

- capabilities

- restrictions

- referrals

- operations

- governance/policy handling

- app configuration or activation safety

This is **augmentation of an existing relationship**, not an onboarding gate by itself.

## What the review request record should hold

Add one small slice-owned review request record in `resources/models.py`.

Recommended shape:

```python
class ResourceAdminReviewRequest(db.Model):
    ulid
    resource_entity_ulid
    review_kind              # "mou_impact_review"
    source_status            # pending_review | approved | rejected | cancelled

    mou_status_before        # optional snapshot
    readiness_status_before  # optional snapshot

    title
    summary
    context_json

    requested_at_utc
    requested_by_ulid
    resolved_at_utc
    resolved_by_ulid
    resolution_note
```

Minimal is better. This object exists to be the thing opened, resolved, and closed.

## What goes in `context_json`

Keep it focused on **app impact**, not legal prose.

Suggested fields:

- `mou_attachment_ref`

- `service_impacts`

- `restriction_impacts`

- `referral_impacts`

- `operations_impacts`

- `governance_impacts`

- `required_app_changes`

- `testing_notes`

- `activation_notes`

That gives Admin a concrete “what had to change in the app?” view.

## DTOs to declare in `resources_v2.py`

Declare the public DTOs in the contract, not the mapper. That matches your canon.

Use this shape:

```python
@dataclass(frozen=True)
class MOUAdminIssueRequestDTO:
    source_ref_ulid: str          # review_request_ulid
    subject_ref_ulid: str | None  # resource entity ULID
    actor_ulid: str | None
    request_id: str


@dataclass(frozen=True)
class MOUAdminReviewPageDTO:
    review_request_ulid: str
    source_ref_ulid: str
    subject_ref_ulid: str | None

    issue_kind: str
    source_status: str
    title: str
    summary: str

    facts: Mapping[str, Any]
    allowed_decisions: tuple[str, ...]
    as_of_utc: str


@dataclass(frozen=True)
class MOUAdminIssueResolveDTO:
    review_request_ulid: str
    decision: str                 # "approve" | "reject"
    actor_ulid: str | None
    request_id: str
    note: str | None = None


@dataclass(frozen=True)
class MOUAdminIssueResolutionDTO:
    review_request_ulid: str
    source_ref_ulid: str
    subject_ref_ulid: str | None

    decision: str
    source_status: str
    close_reason: str
    admin_receipt: AdminIssueReceiptDTO | None
    happened_at_utc: str
```

## Service responsibilities in `resources/admin_review_services.py`

### `raise_mou_admin_issue()`

Creates or refreshes the review request row, then upserts the Admin inbox item.

It should:

- validate resource exists

- create or refresh one open review request for this MOU-impact event

- build `AdminIssueUpsertDTO`

- use a real GET launch target

- flush, not commit

### `mou_review_get()`

Pure read.

It should return:

- resource identity

- current readiness

- current mou status

- review request summary

- app-impact facts

- `allowed_decisions = ("approve", "reject")`

No mutation. No close.

### `resolve_mou_admin_issue()`

The real write path.

It should:

1. load review request

2. verify still actionable

3. apply the decision inside Resources

4. emit Resources-owned audit/ledger

5. terminalize the review request

6. call `close_mou_admin_issue()`

7. return result DTO

### `close_mou_admin_issue()`

Calls Admin close with:

- `source_slice="resources"`

- `issue_kind="mou_impact_review_required"`

- `source_ref_ulid=<review_request_ulid>`

- `source_status=<approved|rejected|cancelled>`

- `close_reason=<boring machine reason>`

- `admin_status="resolved"` normally, or `"source_closed"` if the request died elsewhere

That follows the close-seam canon exactly.

## What approval should mutate

Approval should mutate only the truths related to “MOU app impact has been handled.”

That likely means:

- mark the review request approved

- clear any pending MOU-review-needed flag

- record reviewer + resolved timestamp

- possibly update a Resources app-impact-ready flag if you add one

- possibly permit activation only if your current Resources model actually gates on this

It should **not** broadly rewrite Resource truth just because a review happened.

## What rejection should mutate

Rejection should:

- mark the review request rejected

- record reviewer + note

- preserve the relationship if that is still your intent

- mark any app-impact gating truth that prevents safe activation/use

Rejection means “not app-compatible as currently framed,” not “delete the partner.”

## Route shape in `resources/admin_review_routes.py`

Use dedicated intervention routes only:

- `GET /resources/admin-review/mou/<review_request_ulid>`

- `POST /resources/admin-review/mou/<review_request_ulid>/approve`

- `POST /resources/admin-review/mou/<review_request_ulid>/reject`

And endpoint names like:

- `resources.mou_review_get`

- `resources.mou_review_approve`

- `resources.mou_review_reject`

The Admin launch target must point to the GET review surface, not directly to POST approve/reject. That is part of the canon.

## Review page facts to show

Keep the page practical:

- Resource name / ULID

- current readiness status

- current MOU status

- review request ULID

- why the issue was raised

- service/capability impacts

- restrictions / referral impacts

- operations / governance impacts

- required app changes

- whether those changes are documented/tested/activated

This is a system-readiness decision page, not a document browser.

## Resolution target to hand Admin

Use the structured launch target shape you already froze:

```python
AdminResolutionTargetDTO(
    route_name="resources.mou_review_get",
    route_params={"review_request_ulid": review.ulid},
    launch_label="Open MOU impact review",
)
```

That keeps launch honest and refactor-safe.

## What not to do

Do not:

- mix MOU and SLA in one first pass

- use advisory naming for this

- invent fake approval of the whole relationship

- let Admin mutate Resources truth directly

- bury this logic in generic `resources/services.py`

Keep it inside the dedicated Admin-facing lane, per canon.

## Tests to write first

Write only three targeted proofs first.

### 1. Service test: raise

`raise_mou_admin_issue()` creates or refreshes one open review request and upserts one Admin inbox item with:

- correct `issue_kind`

- correct `workflow_key`

- correct `source_ref_ulid`

- correct `subject_ref_ulid`

### 2. Route-access test: GET review surface

- anonymous: unauthenticated

- staff/auditor: forbidden

- admin: allowed

### 3. Service test: resolve

`resolve_mou_admin_issue(decision="approve")`:

- marks review request approved

- closes Admin item with `admin_status="resolved"`

- emits the expected Resources audit/ledger event

Then add the reject twin.

## Build order

Use this order:

1. add review-request model

2. add Resources contract DTOs

3. implement `raise_mou_admin_issue()`

4. implement `mou_review_get()`

5. add GET review route

6. implement `resolve_mou_admin_issue()`

7. add approve/reject POST routes

8. implement `close_mou_admin_issue()`

9. add targeted tests

10. only then copy the pattern to SLA

---

## Resource MOU Impact Review — Deferred Design Questions

This topic is deferred for post-MVP design and implementation.

Resource MOU review is not a routine onboarding step.  
It is an exception-case workflow for agreements whose terms may require  
application-level changes, new controls, new reporting paths, new project  
management structures, or other cross-slice support before execution may  
safely begin.

The purpose of this note is to preserve the open design questions so the  
discussion can resume later without restarting from zero.

### 1. Scope and Trigger Questions

- What kinds of agreements should trigger MOU impact review at all?

- What distinguishes a normal Resource relationship from an agreement that  
  requires formal system compatibility review?

- Is the trigger tied to the existence of an MOU itself, or only to MOU terms  
  that impose material operational, reporting, financial, governance, or  
  maintenance obligations?

- What kinds of agreement changes are significant enough to reopen review?

- What changes are too minor to justify a new or refreshed review request?

### 2. Authority and Decision Questions

- Who is the actual decision-maker for MOU impact review?

- Is this strictly an Admin/System Administrator review, or does it also  
  require Governance or Board involvement?

- What is Staff allowed to do before MOU impact review is complete?

- What decisions belong to System Administration versus Governance versus  
  project/business leadership?

- What does “approval” actually authorize in system terms?

- What does “rejection” actually mean in operational terms?

### 3. Meaning of Approval / Rejection

- Does approval mean the agreement is acceptable overall, or only that the  
  application can safely support its requirements?

- Does rejection mean the agreement is operationally impossible, or only that  
  the current application does not support it?

- Can a rejected review later be reopened after system changes are made?

- Does approval certify only readiness, or also completion of required setup?

### 4. Agreement Identity and Versioning

- What exactly is the object under review: an uploaded document, a document  
  version, a summary record, an attachment reference, or a project-linked  
  agreement object?

- How should agreement revisions be tracked over time?

- Does each material revision create a new review request or refresh an  
  existing open one?

- How should multiple related agreements for one project be handled?

- How should expired, superseded, or withdrawn agreements affect open review  
  requests?

### 5. Cross-Slice Impact Questions

- Which slices may be materially affected by an MOU?

- What kinds of Finance changes may be required, such as grant tracking,  
  reporting, restricted funds handling, disbursement controls, or audit  
  support?

- What kinds of Calendar changes may be required, such as Projects, Tasks,  
  maintenance schedules, funding demands, or project-specific execution flows?

- What kinds of Resources changes may be required, such as capabilities,  
  restrictions, referral rules, operational constraints, or readiness gating?

- What kinds of Governance changes may be required, such as policy updates,  
  reporting duties, approvals, or records retention rules?

- Are there slice interactions not yet modeled that must be identified before  
  implementation begins?

### 6. Impact Taxonomy Questions

- What categories of application impact should be recognized and named?

- Should impact categories distinguish between:
  
  - service capability impacts,
  
  - referral restrictions,
  
  - operational rules,
  
  - maintenance obligations,
  
  - financial controls,
  
  - grant reporting requirements,
  
  - project-management requirements,
  
  - compliance or governance requirements,
  
  - audit and retention requirements?

- Which impact categories are advisory only, and which require blocking  
  readiness review?

### 7. Review Request Record Questions

- What slice should own the MOU impact review request record?

- What should the table be called?

- What fields must be stored to preserve the request over time?

- What must be snapshotted at request creation time versus derived later?

- Should the review request store a free-form narrative, structured impact  
  fields, or both?

- What evidence or attachment references must be preserved with the request?

- What indexing and uniqueness rules are required?

### 8. Workflow and State Questions

- What are the allowed states of an MOU impact review request?

- What are the allowed transitions between those states?

- What events should open, refresh, close, cancel, or supersede a request?

- What happens if the agreement changes while a review is already open?

- What happens if project planning begins before review is complete?

- What happens if required system work is started but not finished?

### 9. Launch and Review Surface Questions

- What should the Admin launch target show?

- What facts must be present on the review page for a meaningful decision?

- What should be shown from the agreement itself versus from slice-owned  
  projections?

- Should the review page show required app changes as a checklist, narrative,  
  structured table, or all three?

- Should the review surface be project-centric, agreement-centric,  
  resource-centric, or some hybrid of those?

### 10. Required Evidence Questions

- What evidence must exist before approval is allowed?

- Must required application changes be merely documented, or also completed?

- Must tests exist before approval?

- Must configuration and policy changes already be activated before approval?

- Must downstream slices prove readiness explicitly?

- What evidence is required for rejection?

### 11. Downstream Readiness Questions

- How should Finance readiness be evaluated and recorded?

- How should Calendar readiness be evaluated and recorded?

- How should Resources readiness be evaluated and recorded?

- How should Governance/policy readiness be evaluated and recorded?

- Does approval require all affected slices to report ready, or can approval be  
  conditional?

- If conditional approval exists, how is that represented and enforced?

### 12. Blocking and Non-Blocking Questions

- When does an MOU impact review block activation or execution?

- When does it merely raise a warning or advisory?

- Can a Resource remain active while an MOU-related review is pending?

- Can a Project be created before the review is complete?

- Can tasks, schedules, or funding demands be drafted before approval?

### 13. Admin Inbox / Workflow Questions

- Should this always be a true intervention workflow rather than an advisory?

- What should the `issue_kind` vocabulary be?

- What should the `workflow_key` vocabulary be?

- What launch label should Admin see?

- What close reasons should exist?

- What conditions should close a request as `resolved` versus `source_closed`?

### 14. Audit and Ledger Questions

- What events must be emitted when review is requested?

- What events must be emitted on approval, rejection, cancellation, or  
  supersession?

- What must be stored in slice truth versus in Ledger?

- What evidence must remain discoverable for later audit?

- What must be preserved to explain why the application was judged compatible  
  or incompatible at that point in time?

### 15. Documentation and Preservation Questions

- What exactly must be preserved for future operators and auditors?

- How should rationale be stored so the decision remains understandable later?

- What notes are operator-facing versus audit-facing?

- What parts of the record are editable after resolution, if any?

- What retention rule should apply to review requests and supporting  
  documentation?

### 16. Relationship to MVP / Post-MVP Questions

- What minimum structures should be canonized now without implementing the full  
  workflow?

- What must remain explicitly deferred until post-MVP?

- What assumptions are safe for MVP that must later be revisited?

- What future implementation dependencies should be called out now so they do  
  not surprise later work?

### 17. Non-Goal Questions

- What should this workflow explicitly not do?

- Should it avoid becoming a legal document management system?

- Should it avoid becoming a general partner-approval workflow?

- Should it avoid forcing every unusual agreement into deep system redesign?

- Should it avoid coupling unrelated slices too tightly?

## Resumption Rule

When this topic returns, the first task is not implementation.  
The first task is to answer the questions above well enough to freeze:

- trigger criteria,

- ownership,

- state machine,

- impact taxonomy,

- required evidence,

- cross-slice readiness expectations,

- and audit/preservation rules.

Only after those are settled should table design, DTOs, routes, and services  
be implemented.

---
