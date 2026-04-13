# Unified Admin-Facing Slice Lane Canon

**Each slice owns one Admin-facing lane in `admin_review_routes.py` and `admin_review_services.py`. That lane may contain both intervention workflows and advisory-only cues, but the two must remain semantically distinct:**

- **Intervention paths may resolve slice truth.**

- **Advisory paths may notify and optionally close without becoming fake approval workflows.**

This is a structural unification, not a semantic collapse.

### Intervention workflow

An intervention workflow is used only when Admin must make, authorize, or  
finalize a real business decision inside the owning slice.

These workflows follow the full Admin-review pattern:

- `raise_<operation>_admin_issue()`

- `<operation>_review_get()`

- `resolve_<operation>_admin_issue()`

- `close_<operation>_admin_issue()`

Intervention workflows may:

- launch Admin into a slice-local review surface,

- mutate slice-owned truth,

- emit slice-owned audit and ledger events,

- and close the Admin inbox item from the owning slice.

### Advisory-only workflow

An advisory-only workflow is used when a slice is notifying Admin of something  
worth seeing, but no Admin decision or approval is required.

These workflows should use patterns such as:

- `publish_<operation>_admin_advisory()`

- optional `<operation>_advisory_get()`

- optional `close_<operation>_admin_advisory()`

Advisory-only workflows may:

- publish a cue into Admin inbox,

- provide a truthful read-only launch target when needed,

- and close the cue later if the source becomes stale, irrelevant, or otherwise  
  non-actionable.

**Advisory-only workflows must not masquerade as approval pipelines.**

**They must not:**

- invent fake review requests,

- expose approve/reject mechanics where none exist,

- or mutate slice truth through an advisory path.

### Boundary rule

Keeping both workflow types in the same dedicated Admin-facing files is  
allowed and preferred when it preserves clarity, reduces structural sprawl,  
and keeps related mechanics together.

This does **not** mean both workflow types are equivalent.

The distinction between intervention and advisory semantics must remain  
explicit in naming, service behavior, route behavior, and DTO design.

### File-lane rule

Per slice, Admin-facing mechanics must remain confined to:

- `admin_review_routes.py`

- `admin_review_services.py`

Supporting DTO staging and page-view shaping may live in `mapper.py`.  
Any additional persistence required by the slice may live in `models.py`.

Admin-facing mechanics must not drift into unrelated generic service modules.

**Example:**

```python
# ------------------
# Intervention
# workflows
# ------------------

def raise_onboard_admin_issue(...): ...
def onboard_review_get(...): ...
def resolve_onboard_admin_issue(...): ...
def close_onboard_admin_issue(...): ...

# ------------------
# Advisory
# workflows
# ------------------

def publish_intake_completed_admin_advisory(...): ...
def close_intake_completed_admin_advisory(...): ...
def publish_assessment_completed_admin_advisory(...): ...
def publish_watchlist_admin_advisory(...): ...
def close_watchlist_admin_advisory(...): ...

# the initiating slice should also kill a stale advisory.
```
