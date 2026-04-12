# 

# Admin Intervention Canon

Admin is a **cue, triage, and launch** surface.  
Admin is **not** the owner of slice truth, business mutation, or repair  
logic.

When a slice requires Admin intervention, the owning slice must:

1. raise a cue into the Admin inbox,
2. provide a real slice-local resolution surface,
3. perform the actual review, approval, rejection, or corrective action  
   inside the owning slice,
4. record its own truth and audit trail inside the owning slice,
5. close the Admin inbox item when the slice reaches terminal state.

**Admin inbox must remain a truthful reflection of slice-owned review state, not a second source of workflow truth.**

### Ownership Rule

Admin owns:

- visibility,
- queueing,
- launch point,
- operator triage state.

The owning slice owns:

- validation,
- business rules,
- state mutation,
- ledger and audit emission,
- terminal completion,
- closure signal back to Admin inbox.

No slice may outsource its business mutation to Admin.

### Required Pattern for Every Admin-Reviewable Operation

Every admin-reviewable operation must provide four parts.

**1. Raise seam**  
A slice-local service that creates or refreshes an Admin inbox item.

The inbox item must carry:

- `source_slice`
- `issue_kind`
- `source_ref_ulid`
- `subject_ref_ulid` when useful
- human title and summary
- machine context payload
- source status
- workflow key
- resolution target

**Raise seam idempotency rule**  
`raise_<operation>_admin_issue()` must be idempotent for the active review request.  
At most one open Admin inbox item may exist for the tuple:

- `source_slice`
- `issue_kind`
- `source_ref_ulid`

If an open item already exists for that tuple, the raise seam must refresh or update it rather than create a duplicate.

**2. Resolution target**  
A real, stable way for Admin to enter the owning slice.

It must not be a hint, placeholder, dead endpoint, or TODO.  
It must resolve to a real slice-local review or resolution surface.

**Resolution target entry rule**  
The `resolution_target` must point to the owning slice’s **GET review surface**, not directly to a mutating action.  
Admin launches into a slice-local review page or review detail surface.  
Approval, rejection, or other terminal actions must occur only through the owning slice’s explicit resolution path.

**3. Resolution service**  
A slice-local service that executes the actual action.

That service must:

- load the source record,
- verify the issue is still actionable,
- perform the mutation,
- emit slice-owned audit and ledger events as appropriate,
- transition the slice-owned source state,
- determine terminal outcome.

**Stale-action rule**  
`resolve_<operation>_admin_issue()` must verify that the review request is still actionable at the time of mutation.

If the review request is already terminal, superseded, cancelled, or otherwise no longer actionable, the service must refuse mutation and return the appropriate terminal outcome.

If the slice truth has changed elsewhere such that the Admin cue is no longer actionable, the owning slice should close the Admin inbox item with `admin_status="source_closed"`.

**4. Close seam**  
A slice-local call that tells Admin inbox the item is terminal.

Normal closure should come from the owning slice after resolution, not from  
Admin manually hand-waving the item away.

**Close seam idempotency rule**  
`close_<operation>_admin_issue()` must be safe to call more than once.  
If the matching Admin inbox item is already terminal, the close seam must not reopen it, duplicate it, or emit conflicting state.

### Uniform Lifecycle

Every admin-reviewable issue must follow this loop:

slice raises cue  
→ Admin inbox displays cue  
→ Admin launches into owning slice  
→ owning slice resolves  
→ owning slice closes inbox item  
→ Admin inbox reflects terminal state

This loop must hold for Resources, Customers, Sponsors, and any future  
slice that requests Admin intervention.

### Uniform Status Discipline

Closure language must remain boring and consistent.

Use:

- `resolved` when the requested action completed successfully
- `source_closed` when slice truth changed elsewhere and the cue is no  
  longer actionable
- `dismissed` when Admin explicitly dismisses a bad or non-actionable cue
- `duplicate` when folded into another item

Default rule:

**`resolved` and `source_closed` are slice-driven outcomes.  
`dismissed` and `duplicate` are Admin triage outcomes.**

### Boundary Rule

Admin inbox may point back into a slice.  
Admin inbox may not become a second business workflow engine.

That means:

- no slice truth stored only in Admin,
- no approval logic owned by Admin,
- no cross-slice repair hacks inside Admin routes,
- no temporary mutation shortcuts in Admin services.

Admin is the mailbox and launch ramp.  
The slice is the workshop.

### Implementation Rule

For each slice and each admin-reviewable operation, define:

- one raise function,
- one resolution entry surface,
- one resolution service,
- one close function.

Uniform shape.  
Slice-local logic.  
No exceptions unless canonized.

### Structural Truth Rule

A route cannot be called secure or hardened until it is:

- registered,
- reachable,
- internally wired,
- capable of executing its owning-slice resolution path,
- and capable of closing the Admin cue honestly.

Until then, it is **UNTERMINATED**.

### Canon Sentence

**Admin owns visibility and launch.  
The owning slice owns truth, mutation, and completion.**

---

## Naming canon

Use a single slice-local operation stem.

Pattern:

- `raise_<operation>_admin_issue()`
- `<operation>_review_get()`
- `resolve_<operation>_admin_issue()`
- `close_<operation>_admin_issue()`

The operation stem is **slice-local** and should be short and boring.

Examples:

- Resources onboarding:
  - `raise_onboard_admin_issue()`
  - `onboard_review_get()`
  - `resolve_onboard_admin_issue()`
  - `close_onboard_admin_issue()`
- Customers referral exception:
  - `raise_referral_admin_issue()`
  - `referral_review_get()`
  - `resolve_referral_admin_issue()`
  - `close_referral_admin_issue()`
- Sponsors grant acceptance review:
  - `raise_grant_acceptance_admin_issue()`
  - `grant_acceptance_review_get()`
  - `resolve_grant_acceptance_admin_issue()`
  - `close_grant_acceptance_admin_issue()`

Do **not** put the slice name in the function stem when the function already  
lives in that slice module.

## Responsibility canon

These four functions each do exactly one thing.

### `raise_<operation>_admin_issue()`

Slice-local service.  
Creates or refreshes the slice-owned review request record, then publishes the  
cue to Admin inbox through `admin_v2`.

### `<operation>_review_get()`

Slice-local read service.  
Loads the review page data for the owning slice. No mutation. No approval.  
No rejection. No Admin inbox close.

### `resolve_<operation>_admin_issue()`

Slice-local write service.  
Performs the real business action inside the owning slice. Updates slice truth,  
emits slice-owned ledger/audit, terminalizes the slice request, then calls  
`close_<operation>_admin_issue()`.

### `close_<operation>_admin_issue()`

Slice-local bridge back to `admin_v2`.  
Tells Admin inbox the slice-owned request is now terminal.

## admin_v2 contract shape

I would replace the raw `resolution_route: str` idea with a structured launch  
target.

  



    from dataclasses import dataclass  
    from typing import Any, Mapping
    
    @dataclass(frozen=True)  
    class AdminResolutionTargetDTO:  
     route_name: str  
     route_params: Mapping[str, str]  
     launch_label: str  
     http_method: str = "GET"
    
    @dataclass(frozen=True)  
    class AdminIssueUpsertDTO:  
     source_slice: str  
     issue_kind: str  
     source_ref_ulid: str  
     subject_ref_ulid: str | None
    severity: str  
    title: str  
    summary: str  
    source_status: str  
    workflow_key: str  
    resolution_target: AdminResolutionTargetDTO  
    context: Mapping[str, Any]  
    opened_at_utc: str | None = None  
    updated_at_utc: str | None = None  
    
    @dataclass(frozen=True)  
    class AdminIssueCloseDTO:  
        source_slice: str  
        issue_kind: str  
        source_ref_ulid: str
        source_status: str  
        close_reason: str  
        admin_status: str  
        closed_at_utc: str | None = None  
    
    @dataclass(frozen=True)  
    class AdminIssueReceiptDTO:  
     inbox_item_ulid: str  
     source_slice: str  
     issue_kind: str  
     source_ref_ulid: str  
     admin_status: str

 

    



## admin_v2 contract functions

```python
def upsert_inbox_item(  
 dto: AdminIssueUpsertDTO,  
) -> AdminIssueReceiptDTO:  
 ...

def close_inbox_item(  
 dto: AdminIssueCloseDTO,  
) -> AdminIssueReceiptDTO | None:  
 ...

def acknowledge_inbox_item(  
 inbox_item_ulid: str,  
 *,  
 actor_ulid: str,  
) -> AdminIssueReceiptDTO:  
 ...

def set_inbox_item_status(  
 inbox_item_ulid: str,  
 *,  
 admin_status: str,  
) -> AdminIssueReceiptDTO:  
 ...
```



That keeps Admin’s job small:  
queue posture, visibility, and launch target only.

## Slice v2 contract shape

Each slice should own its own review DTOs.

Use this pattern per operation.

 

    from dataclasses import dataclass  
    from typing import Any, Mapping
    
    @dataclass(frozen=True)  
    class <Operation>AdminIssueRequestDTO:  
     source_ref_ulid: str  
     subject_ref_ulid: str | None  
     actor_ulid: str | None  
     request_id: str
    
    @dataclass(frozen=True)  
    class <Operation>AdminReviewPageDTO:  
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
    class <Operation>AdminIssueResolveDTO:  
     review_request_ulid: str  
     decision: str  
     actor_ulid: str | None  
     request_id: str  
     note: str | None = None
    
    @dataclass(frozen=True)  
    class <Operation>AdminIssueResolutionDTO:  
     review_request_ulid: str  
     source_ref_ulid: str  
     subject_ref_ulid: str | None
    decision: str  
    source_status: str  
    close_reason: str  
    admin_receipt: AdminIssueReceiptDTO | None  
    happened_at_utc: str



## Slice v2 contract functions

Per slice, per operation:

```python
def raise_<operation>_admin_issue(  
 req: <Operation>AdminIssueRequestDTO,  
) -> AdminIssueReceiptDTO:  
 ...

def <operation>_review_get(  
 review_request_ulid: str,  
) -> <Operation>AdminReviewPageDTO:  
 ...

def resolve_<operation>_admin_issue(  
 req: <Operation>AdminIssueResolveDTO,  
) -> <Operation>AdminIssueResolutionDTO:  
 ...

def close_<operation>_admin_issue(  
 *,  
 review_request_ulid: str,  
 source_status: str,  
 close_reason: str,  
 admin_status: str,  
) -> AdminIssueReceiptDTO | None:  
 ...
```

## Decision canon

Keep decisions boring and shared.

For `decision` in resolve DTOs, allow only slice-relevant terminal actions.

Baseline:

- `"approve"`
- `"reject"`

Later, if a slice truly needs more:

- `"cancel"`
- `"send_back"`
- `"mark_complete_without_action"`

Do not add more until a real slice requires it.

## Status canon

Keep source status and admin status separate.

### Source status

Owned by the slice.  
Examples:

- `pending_review`
- `approved`
- `rejected`
- `cancelled`

### Admin status

Owned by Admin.  
Use only:

- `open`
- `acknowledged`
- `in_review`
- `snoozed`
- `resolved`
- `source_closed`
- `dismissed`
- `duplicate`

Rule:  
`resolve_*_admin_issue()` should normally close Admin with  
`admin_status="resolved"`.

`close_*_admin_issue()` may also be called from other slice events when the  
source becomes non-actionable, in which case use  
`admin_status="source_closed"`.

## Resolution target canon

## Resolution target canon

The launch target must be a real slice entry surface and must resolve to the  
owning slice’s **GET review surface**.

Use:

```python
AdminResolutionTargetDTO(  
    route_name="resources.onboard_review_get",  
    route_params={"review_request_ulid": review.ulid},  
    launch_label="Open resource onboarding review",  
)
```

Do **not** store only a plain URL string if you can avoid it.  
A structured route target is easier to validate, easier to test, and less  
fragile during refactors.

Do **not** point the resolution target directly at approve/reject POST routes.

## Workflow key canon

Use a stable machine key for grouping/reporting.

Examples:

- `resource_onboard_review`
- `customer_referral_review`
- `sponsor_grant_acceptance_review`

That key should stay stable even if the route names later change.

## issue_kind canon

Use operation-specific machine truth, not vague prose.

Examples:

- `onboard_review_required`
- `referral_review_required`
- `grant_acceptance_review_required`

That is what Admin uses for dedupe and reporting.

## Concrete Resources example

This is the shape I would move Resources toward:

```python
@dataclass(frozen=True)  
class OnboardAdminIssueRequestDTO:  
 source_ref_ulid: str # review_request_ulid  
 subject_ref_ulid: str | None # resource entity ULID  
 actor_ulid: str | None  
 request_id: str

@dataclass(frozen=True)  
class OnboardAdminReviewPageDTO:  
 review_request_ulid: str  
 source_ref_ulid: str  
 subject_ref_ulid: str | None  
 issue_kind: str  
 source_status: str  
 title: str  
 summary: str  
 facts: dict[str, object]  
 allowed_decisions: tuple[str, ...]  
 as_of_utc: str

Functions:

def raise_onboard_admin_issue(  
 req: OnboardAdminIssueRequestDTO,  
) -> AdminIssueReceiptDTO:  
 ...

def onboard_review_get(  
 review_request_ulid: str,  
) -> OnboardAdminReviewPageDTO:  
 ...

def resolve_onboard_admin_issue(  
 req: OnboardAdminIssueResolveDTO,  
) -> OnboardAdminIssueResolutionDTO:  
 ...

def close_onboard_admin_issue(  
 *,  
 review_request_ulid: str,  
 source_status: str,  
 close_reason: str,  
 admin_status: str = "resolved",  
) -> AdminIssueReceiptDTO | None:  
 ...
```

### `source_ref_ulid` in Admin inbox always points to the slice-owned review request ULID.

**`source_ref_ulid` = slice-owned review request ULID**  
**`subject_ref_ulid` = business object ULID**

That makes the queue item about the review request itself, which is the thing  
being opened, resolved, and closed.

## Final freeze

**Admin v2 owns inbox DTOs and queue posture.**  
**Each slice v2 owns review DTOs and resolution services.**  
**Every admin-reviewable operation exposes raise, review_get, resolve, and close with the same naming pattern.** 
**Resolution targets launch only into slice-local GET review surfaces.** 
**Raise and close seams must be idempotent.** 
**Mappers shape view data only and never mutate workflow truth.**

That gives you one repeatable admin-review pipeline across the app:  
cue, launch, resolve in owning slice, close from owning slice.

### Function pattern freeze:

- `raise_<operation>_admin_issue()`
- `<operation>_review_get()`
- `resolve_<operation>_admin_issue()`
- `close_<operation>_admin_issue()`

That gives you one repeatable admin-review pipeline across the app:  
cue, launch, resolve in owning slice, close from owning slice.

### Dedicated Routes & Services files:

Admin-review code must live in dedicated `admin_review_routes.py` and  
`admin_review_services.py` files inside the owning slice so review mechanics  
do not drift into unrelated service modules or mutate slice truth through  
side doors.

```bash
app/
  extensions/
    contracts/
      admin_v2.py
      resources_v2.py
      customers_v2.py
      sponsors_v2.py

  slices/
    <slice>/
      admin_review_routes.py
      admin_review_services.py
      mapper.py
      models.py
```



### Responsibility split:

- `extensions/contracts/*.py`
  - public cross-slice seam only
  - stable function signatures
  - contract DTO types
  - no buried business logic
- `slices/<slice>/admin_review_routes.py`
  - thin entry points only
  - GET review surface
  - POST decision actions
  - auth/RBAC at the route edge
  - call contract or slice-local review service, then respond
- `slices/<slice>/admin_review_services.py`
  - all admin-review mechanics for that slice
  - load review request
  - validate actionable state
  - perform slice-owned mutation
  - emit audit/ledger
  - close Admin inbox item
- `slices/<slice>/mapper.py`
  - DTO assembly
  - projection/view shaping
  - response package shaping
  - keep route/service code from becoming serialization soup
- `slices/<slice>/models.py`
  - any review-request tables or related persistence
  - only if the slice truly needs stored review-request state

**Mapper boundary rule**  
`mapper.py` may shape DTO payloads, staged facts, and page-view projections.  
`mapper.py` must not:

- decide review outcomes,
- mutate review state,
- emit ledger or audit events,
- close Admin inbox items,
- or perform cross-slice workflow actions.

Those responsibilities belong only to slice services, especially  
`admin_review_services.py`.
