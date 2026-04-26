## Admin intervention refit TODO



## Phase 11 — tests to flush stale `admin_v1` calls

This phase should be intentionally unforgiving.

### 11A — retired contract tripwire tests

- Add test: every public `admin_v1` function raises `RetiredAdminV1Error`

- Add test: exception message mentions `admin_v1` retired and `admin_v2`

- Add test: importing/using any still-exposed `admin_v1` helper path fails loudly

### 11B — source scan / stale reference tests

- Add regression test or audit script that fails on live code references to:
  
  - `admin_v1`
  
  - `AdminInbox`
  
  - `issue_kind`
  
  - `source_ref_ulid`
  
  - `subject_ref_ulid`
  
  - `resolution_route`
  
  - `review_kind`
  
  - `AdminReviewRequest`
  
  - `admin_review_routes`
  
  - `admin_review_services`

- Exclude only:
  
  - intentional retirement stub file for `admin_v1`
  
  - migration notes/docs where historical mention is acceptable

- Make exclusions explicit and tiny

### 11C — contract path tests

- Add tests proving migrated slices call `admin_v2`, not `admin_v1`

- For Resources:
  
  - raise path uses `admin_v2.upsert_alert()`
  
  - close path uses `admin_v2.close_alert()`

- Repeat same expectation for Sponsors

- Repeat same expectation for Customers

### 11D — end-to-end flow tests

For each of Resources, Sponsors, Customers:

- slice-local issue row created

- `admin_alert` row created/upserted

- Admin Inbox can display it

- GET issue page loads from slice-local route

- POST resolution mutates in slice

- Admin alert closes honestly

- slice-owned audit / event emission still happens

### 11E — negative path tests

- stale/terminal issue cannot be resolved twice

- stale/terminal issue returns or closes as `source_closed` where appropriate

- Admin triage actions do not mutate slice truth

- missing or bad structured launch targets fail clearly

### 11F — dedupe tests

- exact live duplicate blocked for same:
  
  - `source_slice`
  
  - `reason_code`
  
  - `request_id`
  
  - `target_ulid`

- same `source_slice`

- same `reason_code`

- same `target_ulid`

- different `request_id`

- must be allowed as separate live alerts

- archive/terminal behavior does not break new live inserts

### 11G — migration residue tests

- test that old table/model names are no longer imported in live slice code

- test that current SQLAlchemy metadata contains new AdminIssue tables

- test that old review-request tables are absent after migration

- test that staged future-slice `*_admin_issue` tables exist where intended


