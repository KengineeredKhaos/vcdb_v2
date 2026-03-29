# 

Admin Intervention Overlay Pattern

Admin intervention is an exception-path mechanism, not a default workflow
pattern.

Ordinary slice work should remain inside the slice’s normal operator
workflow, protected by RBAC and recorded by the slice’s normal Ledger
events. Admin intervention should be introduced only when a slice has a
real need for authority separation, policy-controlled exception handling,
or explicit second-party review.

When Admin intervention is required, it should be added as a discrete
slice-local overlay, not by piggy-backing on existing workflow services,
and not by piling side effects into ordinary routes or page-render
helpers.

Core rule

Slice owns truth. Admin owns operator view.

Expanded form:

The owning slice retains authority over truth, semantics, validation,
state transitions, and corrective commands.
Admin is limited to observation, read-side composition, triage UX, and
operator launch shells.

Admin may present a privileged action, but the action must execute
through the owning slice’s interface. Admin may frame, preview, and
launch the workflow, but it must not absorb foreign business logic,
foreign validation, foreign write semantics, or foreign audit meaning.

Required overlay structure inside a slice

If a slice needs Admin intervention, it should add a dedicated overlay
package/module set rather than modifying the ordinary working path
directly.

Recommended shape:

<slice>/admin_review_services.py
<slice>/admin_review_routes.py
<slice>-owned review request model/table, if persistent request tracking
is required

Purpose of the overlay

The overlay is the slice-local airlock between:

1. the slice’s normal business workflow, and
2. the Admin inbox/control-surface workflow.

The overlay owns the Admin-intervention lifecycle for that slice and that
slice only.

What the overlay should own

1. Opening a slice-owned Admin review/intervention request
2. Mapping that request into the Admin inbox contract/envelope
3. Building a small non-PII summary/context payload for Admin display
4. Defining the slice-specific resolution actions
5. Applying slice-local state changes during approval/rejection/resolution
6. Staging slice-local Ledger/event_bus emission
7. Closing the Admin inbox item after the owning slice reaches terminal
   resolution
8. Flushing slice-local DB changes

What the overlay should not own

1. Ordinary workflow progression that does not truly require Admin
2. The Admin inbox table or Admin queue semantics
3. Cross-slice data ownership
4. Direct commit/rollback boundaries
5. General-purpose catch-all admin business logic

Where commit belongs

Services flush.
Routes commit.

The overlay service module may update slice-local records, stage
event_bus.emit(...), and close the Admin inbox item, but the final
db.session.commit() belongs in the overlay route that handles the Admin
operator’s action.

This means the route that originally submitted the request for Admin
review is not the same route that resolves it later. Request creation and
request resolution are separate HTTP transactions with separate commit
boundaries.

Lifecycle pattern

1. Slice workflow detects a true need for Admin intervention
2. Slice overlay opens a slice-owned request record
3. Slice overlay publishes a notice to Admin inbox through the Admin
   contract
4. Admin inbox surfaces the item
5. Admin operator launches the owning-slice resolution route
6. Slice overlay resolves the request, applies slice-local changes,
   stages Ledger/event_bus emission, and closes the Admin inbox item
7. Route commits
8. Admin inbox item leaves the active queue and later archives per Admin
   retention policy

Request ownership rule

Admin inbox items are not the authoritative approval/authorization
record.

If persistent review tracking is needed, the owning slice must own a real
review/intervention request record. Admin inbox receives only a queue
notice pointing at that slice-owned request.

No-reopen rule

Admin intervention requests should normally follow a no-reopen rule.

Once a slice-owned request reaches terminal closure, it stays terminal.
If further Admin intervention is needed later, the owning slice should
open a new request rather than mutating or reopening the old one.

Why this overlay pattern exists

This pattern allows a slice to add true Admin intervention without:

- polluting ordinary workflow services
- creating side effects in page rendering or review snapshots
- overloading existing routes with special-case approval logic
- making Admin the owner of slice semantics
- turning every workflow into a bottlenecked approval engine

Design caution

Do not add Admin intervention just because the infrastructure exists.

Use it only when:

- authority separation is actually required
- policy requires a second party or exception path
- the risk/impact of the action justifies the added workflow cost

Otherwise, keep the work inside the normal slice workflow, trust the
authorized operator, enforce RBAC, and record the action in Ledger.

Practical takeaway

If real Admin intervention is needed in a slice, add it as a separate,
bounded overlay package that the slice workflow calls into deliberately.
Do not smear Admin-review behavior across ordinary services, ordinary
routes, or page-render helpers.
