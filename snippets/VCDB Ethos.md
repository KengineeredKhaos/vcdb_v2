# VCDB Ethos

- **Skinny routes, fat services.** Routes only orchestrate; all logic lives in services.

- **Slices own their data.** Each slice reads/writes only its tables; no cross-slice DB reach-arounds.

- **Extensions is the only bridge.** All inter-slice calls go through **extensions/contracts** (facades), not direct imports.

- **Contracts are versioned.** Add `v2` next to `v1`; never mutate `v1` in place.

- **DTOs + JSON Schema at the boundary.** Requests/responses validated at the contract layer.

- **ULID everywhere.** One **entity_ulid** from creation to archive; all events, refs, and joins use ULIDs.

- **Time = UTC (ISO-8601 Z).** Persist in UTC; present local time in the UI only.

- **Ledger is the audit spine.** Append-only, content-hashed, cross-links to domain records; no PII.

- **RBAC ≠ domain roles.** RBAC (admin/user/auditor) lives in **auth**; domain roles (customer/resource/sponsor/…) live in **entity/governance**.

- **Nothing is deleted.** Data is archived per Governance retention; all state changes are ledgered.
