# Resource SLA Impact Review — Deferred Design Questions

**This topic is deferred for post-MVP design and implementation.**

**MOU review asks whether the application can support the agreement’s structural and policy implications.**

**SLA review asks whether the application can support, track, and enforce the agreement’s operational service commitments.**

**Resource SLA review is not a routine onboarding step.**  
It is an exception-case workflow for agreements whose service-level terms may  
require application-level support for availability, capacity, response-time  
tracking, blackout dates, escalation handling, scheduling, maintenance  
obligations, or other operational controls before execution may safely begin.

The purpose of this note is to preserve the open design questions so the  
discussion can resume later without restarting from zero.

### 1. Scope and Trigger Questions

- What kinds of service-level agreements should trigger SLA impact review at  
  all?

- What distinguishes a normal service arrangement from one that requires formal  
  system compatibility review?

- Is the trigger tied to the existence of an SLA itself, or only to SLA terms  
  that impose material scheduling, capacity, monitoring, escalation, or  
  reporting obligations?

- What kinds of SLA changes are significant enough to reopen review?

- What changes are too minor to justify a new or refreshed review request?

### 2. Authority and Decision Questions

- Who is the actual decision-maker for SLA impact review?

- Is this strictly an Admin/System Administrator review, or does it also  
  require management or Governance participation in some cases?

- What is Staff allowed to do before SLA impact review is complete?

- What decisions belong to System Administration versus operational leadership?

- What does “approval” actually authorize in system terms?

- What does “rejection” actually mean in operational terms?

### 3. Meaning of Approval / Rejection

- Does approval mean the SLA is acceptable overall, or only that the  
  application can safely support and track its operational requirements?

- Does rejection mean the SLA is operationally impossible, or only that the  
  current application does not support it?

- Can a rejected review later be reopened after system changes are made?

- Does approval certify only readiness, or also completion of required setup?

### 4. Agreement Identity and Versioning

- What exactly is the object under review: an uploaded document, a document  
  version, a summary record, an attachment reference, or a service profile  
  object?

- How should SLA revisions be tracked over time?

- Does each material revision create a new review request or refresh an  
  existing open one?

- How should multiple related SLA documents for one Resource be handled?

- How should expired, superseded, or withdrawn SLAs affect open review  
  requests?

### 5. Cross-Slice Impact Questions

- Which slices may be materially affected by an SLA?

- What kinds of Resources changes may be required, such as capacity limits,  
  service constraints, availability truth, or referral promises?

- What kinds of Calendar changes may be required, such as task generation,  
  maintenance schedules, blackout dates, response deadlines, or escalation  
  reminders?

- What kinds of Governance or policy changes may be required, such as service  
  standards, retention rules, or oversight requirements?

- What kinds of Finance changes may be required, if SLA terms carry penalties,  
  reimbursements, incentives, or reporting obligations?

- Are there slice interactions not yet modeled that must be identified before  
  implementation begins?

### 6. Impact Taxonomy Questions

- What categories of application impact should be recognized and named?

- Should impact categories distinguish between:
  
  - hours of operation,
  
  - service windows,
  
  - response-time obligations,
  
  - fulfillment-time obligations,
  
  - capacity ceilings,
  
  - blackout periods,
  
  - escalation paths,
  
  - maintenance schedules,
  
  - reporting/monitoring requirements,
  
  - exception handling?

- Which impact categories are advisory only, and which require blocking  
  readiness review?

### 7. Review Request Record Questions

- What slice should own the SLA impact review request record?

- What should the table be called?

- What fields must be stored to preserve the request over time?

- What must be snapshotted at request creation time versus derived later?

- Should the review request store a free-form narrative, structured impact  
  fields, or both?

- What evidence or attachment references must be preserved with the request?

- What indexing and uniqueness rules are required?

### 8. Workflow and State Questions

- What are the allowed states of an SLA impact review request?

- What are the allowed transitions between those states?

- What events should open, refresh, close, cancel, or supersede a request?

- What happens if the SLA changes while a review is already open?

- What happens if scheduling or service commitments begin before review is  
  complete?

- What happens if required system work is started but not finished?

### 9. Launch and Review Surface Questions

- What should the Admin launch target show?

- What facts must be present on the review page for a meaningful decision?

- What should be shown from the SLA itself versus from slice-owned  
  projections?

- Should the review page show required app changes as a checklist, narrative,  
  structured table, or all three?

- Should the review surface be resource-centric, schedule-centric,  
  service-window-centric, or some hybrid?

### 10. Required Evidence Questions

- What evidence must exist before approval is allowed?

- Must required scheduling/capacity logic be merely documented, or also  
  completed?

- Must tests exist before approval?

- Must monitoring, reminders, or escalation mechanics already be activated  
  before approval?

- Must downstream slices prove readiness explicitly?

- What evidence is required for rejection?

### 11. Downstream Readiness Questions

- How should Resources readiness be evaluated and recorded?

- How should Calendar readiness be evaluated and recorded?

- How should monitoring or alerting readiness be evaluated and recorded?

- Does approval require all affected slices to report ready, or can approval be  
  conditional?

- If conditional approval exists, how is that represented and enforced?

### 12. Blocking and Non-Blocking Questions

- When does an SLA impact review block activation or execution?

- When does it merely raise a warning or advisory?

- Can a Resource remain active while an SLA-related review is pending?

- Can schedules, tasks, or referrals be drafted before approval?

- Can commitments appear in operator-facing workflows before review is complete?

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

- Should it avoid becoming a full service monitoring platform?

- Should it avoid becoming a general schedule-management substitute for normal  
  Calendar planning?

- Should it avoid forcing every change in hours or capacity into deep review?

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
