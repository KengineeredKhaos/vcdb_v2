# Punch List

Got it. Based on what’s in `pasted.txt` (compileall + Ruff per-slice) and your Ruff run on `app/extensions`, here’s an updated **punch list + recommended fix order**.

## Current status snapshot

### ✅ “Green enough to build on” (Ruff clean)

- `attachments`, `customers`, `ledger`, `logistics` — all checks passed.

### 🟡 “Mostly fine, small fixes”

- `admin` — had 5 Ruff errors but they were auto-fixed.

- `auth` — `__init__.py` has import-order + unused import issues.

### 🔴 “Not ready” (real blockers for slice-gates)

- `calendar` — failures are in `app/slices/calendar/Chat/Calendar_slice_services.py` (undefined `Task`, etc.).

- `entity` — undefined `allowed_role_codes`, `current_actor_ulid`, plus one small unused var.

- `finance` — missing imports/constants/models + naming lint; 20 remaining after many auto-fixes.

- `governance` — example route file + `services.py` references missing `POLICY_REGISTRY`, `_policy_upsert`, `set_policy`.

- `resources` / `sponsors` — cross-slice ORM relationship type hints (`EntityOrg`, `EntityPerson`) causing Ruff failures.

- `app/extensions` — lots of B904 “raise without from”; one invalid `# noqa` code.

Also: `compileall` ran clean across slices, so we’re dealing with structural/refactor hygiene rather than syntax breakage.

---

## Punch list (prioritized)

### 1) Remove “scratch/example code” from runtime packages (fast wins, high signal)

These are currently poisoning slice readiness:

- **Calendar**: `app/slices/calendar/Chat/*` is failing Ruff (undefined `Task`). If “Chat” is scratch, the clean move is:
  
  - move it out of `app/slices/calendar/` entirely (e.g., `docs/` or `scratch/` outside the package), **or**
  
  - add it to Ruff excludes, **or**
  
  - delete it (best if it’s disposable).

- **Governance**: `governance_routes_example_.py` is an example file with missing imports (`current_app`). Same treatment: relocate outside the package or delete.

This alone will make your “slice-health” gates much cleaner and less noisy.

---

### 2) Fix “architectural boundary leaks” in Resources and Sponsors models

Those `EntityOrg` / `EntityPerson` relationships are a red flag **and** currently break Ruff.

Given your ethos (“no cross-slice table imports”), the best fix is:

- **Remove ORM relationships to Entity models entirely** from Resources/Sponsors.

- Keep only the ULID columns (e.g., `org_ulid`, `person_ulid`) and resolve details through the **Entity contract** at service/query time.

This is both:  
✅ passes Ruff and  
✅ restores your slice boundary rule.

---

### 3) Make Governance services internally consistent

`app/slices/governance/services.py` references names that don’t exist (`POLICY_REGISTRY`, `_policy_upsert`, `set_policy`).

This is the kind of “half-refactor seam” that will keep biting you.

What to do:

- Decide whether Governance policy writing lives in:
  
  - **Admin slice** (preferred for durable admin-grade editing), with Governance exposing read-only via contracts, **or**
  
  - Governance itself with a very tight `services_admin.py` provider (your allowed exception).

- Then delete/replace these dangling helpers so Governance is either:
  
  - purely “policy files + validation + read-only loaders”, or
  
  - a complete policy store with a registry and upsert path.

Right now it’s neither.

---

### 4) Fix Entity slice undefined names (small, but blocks routes)

`allowed_role_codes()` and `current_actor_ulid()` are undefined in `entity/routes.py`.

Your decision point:

- If “role codes” come from Governance policy → provide them via **extensions/contracts/governance_v2** (read-only) or an Entity-local helper that calls that contract.

- If “actor ULID” comes from request context → centralize it in **one place** (request_ctx helper / auth contract) and import it consistently.

This is a clean, bounded fix once you pick the source of truth.

---

### 5) Finance: resolve the remaining 20 Ruff errors as a single “stabilize” pass

Finance still has:

- missing constants (`ALLOWED_PERIOD_STATUS`)

- missing imports (`func`, `List`)

- missing model symbols (`Grant`, `Reimbursement`)

- missing helper `_external_restriction_type`

- variable naming lint (`l`)

- small unused-vars cleanup in reporting

This is a classic “one module at a time” sweep:

1. fix `services_funds.py` (imports/constants/helpers)

2. fix `services_grants.py` (model imports)

3. rename ambiguous loop vars in `services_journal.py`

4. clean the unused report aggregates

Once Finance is Ruff-clean, you can add a `finance-health` gate like you have for policy-health.

---

### 6) Extensions contracts: fix B904 and the invalid noqa

You’ve got lots of:

> “Within an except clause, raise with `raise ... from err` …”

This is a mechanical cleanup:

- change `raise _as_contract_error(where, exc)` to `raise _as_contract_error(where, exc) from exc`

- fix the invalid rule code (`# noqa: B902` isn’t valid per Ruff’s warning)

Not urgent for functionality, but great to make “contracts are clean boundaries” true.

---

## Yes: back to “per-slice pre-UI build-out checks”

Exactly. Your Logistics win is the proof-of-pattern: **policy-driven behavior + lint + health checks + slice-local reads/writes**.

The next move is to formalize a repeatable gate:

### `flask dev slice-health --all`

Outputs a checklist per slice:

- compileall ✅/❌

- ruff ✅/❌

- slice-specific health checks ✅/⚠️/❌ (policy-health, finance-health, entity-health, etc.)

You’ve already built the template with `policy-lint` + `policy-health`.



---

## Compile Tests:

(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ python -m compileall app/slices/admin
Listing 'app/slices/admin'...
Listing 'app/slices/admin/templates'...
Listing 'app/slices/admin/templates/admin'...
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ python -m compileall app/slices/attachments
Listing 'app/slices/attachments'...
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ python -m compileall app/slices/auth
Listing 'app/slices/auth'...
Listing 'app/slices/auth/data'...
Listing 'app/slices/auth/data/schemas'...
Listing 'app/slices/auth/templates'...
Listing 'app/slices/auth/templates/auth'...
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ python -m compileall app/slices/calendar
Listing 'app/slices/calendar'...
Listing 'app/slices/calendar/Chat'...
Listing 'app/slices/calendar/templates'...
Listing 'app/slices/calendar/templates/calendar'...
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ python -m compileall app/slices/customers
Listing 'app/slices/customers'...
Listing 'app/slices/customers/templates'...
Listing 'app/slices/customers/templates/customers'...
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ python -m compileall app/slices/entity
Listing 'app/slices/entity'...
Listing 'app/slices/entity/templates'...
Listing 'app/slices/entity/templates/entity'...
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ python -m compileall app/slices/finance
Listing 'app/slices/finance'...
Listing 'app/slices/finance/templates'...
Listing 'app/slices/finance/templates/finanace'...
Listing 'app/slices/finance/templates/finance'...
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ python -m compileall app/slices/governance
Listing 'app/slices/governance'...
Listing 'app/slices/governance/data'...
Listing 'app/slices/governance/data/schemas'...
Listing 'app/slices/governance/templates'...
Listing 'app/slices/governance/templates/governance'...
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ python -m compileall app/slices/ledger
Listing 'app/slices/ledger'...
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ python -m compileall app/slices/logistics
Listing 'app/slices/logistics'...
Listing 'app/slices/logistics/data'...
Listing 'app/slices/logistics/data/schemas'...
Listing 'app/slices/logistics/templates'...
Listing 'app/slices/logistics/templates/logistics'...
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ python -m compileall app/slices/resources
Listing 'app/slices/resources'...
Listing 'app/slices/resources/templates'...
Listing 'app/slices/resources/templates/resources'...
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ python -m compileall app/slices/sponsors
Listing 'app/slices/sponsors'...
Listing 'app/slices/sponsors/templates'...
Listing 'app/slices/sponsors/templates/sponsors'...
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ ruff check app/slices/admin
Found 5 errors (5 fixed, 0 remaining).
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ ruff check app/slices/attachments
All checks passed!




---

## Ruff Checks

(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ ruff check app/slices/auth
E402 Module level import not at top of file
  --> app/slices/auth/__init__.py:61:1
   |
59 | )
60 |
61 | from . import models
   | ^^^^^^^^^^^^^^^^^^^^
   |

F401 `.models` imported but unused; consider removing, adding to `__all__`, or using a redundant alias
  --> app/slices/auth/__init__.py:61:15
   |
59 | )
60 |
61 | from . import models
   |               ^^^^^^
   |
help: Add unused import `models` to __all__

F401 `flask.url_for` imported but unused
   --> app/slices/auth/__init__.py:166:42
    |
164 |     """
165 |
166 |     from flask import redirect, request, url_for
    |                                          ^^^^^^^
167 |
168 |     if not current_app.debug:
    |
help: Remove unused import: `flask.url_for`

Found 4 errors (1 fixed, 3 remaining).
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ ruff check app/slices/calendar
F821 Undefined name `Task`
  --> app/slices/calendar/Chat/Calendar_slice_services.py:77:24
   |
76 | def task_view(task_ulid: str) -> dict:
77 |     t = db.session.get(Task, task_ulid)
   |                        ^^^^
78 |     if t is None:
79 |         raise LookupError("task not found")
   |

F821 Undefined name `Task`
   --> app/slices/calendar/Chat/Calendar_slice_services.py:284:9
    |
282 |         }
283 |
284 |     t = Task(
    |         ^^^^
285 |         project_ulid=project_ulid,
286 |         task_title=task_title.strip(),
    |

F821 Undefined name `Task`
   --> app/slices/calendar/Chat/Calendar_slice_services.py:407:26
    |
405 | def list_tasks_for_project(project_ulid: str) -> list[dict]:
406 |     rows = (
407 |         db.session.query(Task)
    |                          ^^^^
408 |         .filter(Task.project_ulid == project_ulid)
409 |         .order_by(Task.created_at_utc.asc())
    |

F821 Undefined name `Task`
   --> app/slices/calendar/Chat/Calendar_slice_services.py:408:17
    |
406 |     rows = (
407 |         db.session.query(Task)
408 |         .filter(Task.project_ulid == project_ulid)
    |                 ^^^^
409 |         .order_by(Task.created_at_utc.asc())
410 |         .all()
    |

F821 Undefined name `Task`
   --> app/slices/calendar/Chat/Calendar_slice_services.py:409:19
    |
407 |         db.session.query(Task)
408 |         .filter(Task.project_ulid == project_ulid)
409 |         .order_by(Task.created_at_utc.asc())
    |                   ^^^^
410 |         .all()
411 |     )
    |

Found 17 errors (12 fixed, 5 remaining).
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ ruff check app/slices/customers
All checks passed!
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ ruff check app/slices/entity
F821 Undefined name `allowed_role_codes`
  --> app/slices/entity/routes.py:68:33
   |
67 |     role = (request.args.get("role") or "").strip().lower() or None
68 |     if role and role not in set(allowed_role_codes()):
   |                                 ^^^^^^^^^^^^^^^^^^
69 |         return jsonify({"ok": False, "error": f"invalid role '{role}'"}), 400
   |

F821 Undefined name `allowed_role_codes`
   --> app/slices/entity/routes.py:113:19
    |
111 |         per = 20
112 |
113 |     allowed = set(allowed_role_codes())
    |                   ^^^^^^^^^^^^^^^^^^
114 |     default_roles = [r for r in ("resource", "sponsor") if r in allowed]
    |

F821 Undefined name `allowed_role_codes`
   --> app/slices/entity/routes.py:163:20
    |
161 |     return render_template(
162 |         "entity/create.html",
163 |         role_codes=allowed_role_codes(),
    |                    ^^^^^^^^^^^^^^^^^^
164 |         states=us_state_choices,
165 |     )
    |

F821 Undefined name `current_actor_ulid`
   --> app/slices/entity/routes.py:184:13
    |
183 |     req_id = new_ulid()
184 |     actor = current_actor_ulid()
    |             ^^^^^^^^^^^^^^^^^^
185 |
186 |     env = entity_contract.ContractEnvelope(
    |

F841 Local variable `created` is assigned to but never used
   --> app/slices/entity/services.py:468:9
    |
466 |         )
467 |         db.session.add(addr)
468 |         created = True
    |         ^^^^^^^
469 |     else:
470 |         addr.address1 = _norm(address1) or addr.address1
    |
help: Remove assignment to unused variable `created`

Found 5 errors.
No fixes available (1 hidden fix can be enabled with the `--unsafe-fixes` option).
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ ruff check app/slices/finance
F821 Undefined name `ALLOWED_PERIOD_STATUS`
  --> app/slices/finance/services_funds.py:91:22
   |
89 | def set_period_status(*, period_key: str, status: str) -> None:
90 |     status = status.strip().lower()
91 |     if status not in ALLOWED_PERIOD_STATUS:
   |                      ^^^^^^^^^^^^^^^^^^^^^
92 |         raise ValueError("invalid period status")
93 |     p = db.session.execute(
   |

F821 Undefined name `func`
   --> app/slices/finance/services_funds.py:410:16
    |
408 |     # this fund?”.
409 |     balance_q = (
410 |         select(func.coalesce(func.sum(BalanceMonthly.net_cents), 0))
    |                ^^^^
411 |         .join(
412 |             Account,
    |

F821 Undefined name `func`
   --> app/slices/finance/services_funds.py:410:30
    |
408 |     # this fund?”.
409 |     balance_q = (
410 |         select(func.coalesce(func.sum(BalanceMonthly.net_cents), 0))
    |                              ^^^^
411 |         .join(
412 |             Account,
    |

F821 Undefined name `List`
   --> app/slices/finance/services_funds.py:439:6
    |
437 | def list_funds_with_balances(
438 |     *, include_inactive: bool = False
439 | ) -> List[FundDTO]:
    |      ^^^^
440 |     """
441 |     Slice implementation for finance_v2.list_funds(...).
    |

F821 Undefined name `func`
   --> app/slices/finance/services_funds.py:483:13
    |
481 |         select(
482 |             BalanceMonthly.fund_code,
483 |             func.coalesce(func.sum(BalanceMonthly.net_cents), 0).label(
    |             ^^^^
484 |                 "balance_cents"
485 |             ),
    |

F821 Undefined name `func`
   --> app/slices/finance/services_funds.py:483:27
    |
481 |         select(
482 |             BalanceMonthly.fund_code,
483 |             func.coalesce(func.sum(BalanceMonthly.net_cents), 0).label(
    |                           ^^^^
484 |                 "balance_cents"
485 |             ),
    |

F821 Undefined name `List`
   --> app/slices/finance/services_funds.py:502:13
    |
501 |     # ---- Build DTOs ----
502 |     result: List[FundDTO] = []
    |             ^^^^
503 |
504 |     for fund in funds:
    |

F821 Undefined name `_external_restriction_type`
   --> app/slices/finance/services_funds.py:508:32
    |
506 |         dto.id = fund.ulid
507 |         dto.name = fund.name
508 |         dto.restriction_type = _external_restriction_type(fund.restriction)
    |                                ^^^^^^^^^^^^^^^^^^^^^^^^^^
509 |         dto.starts_on = None  # can be wired later if Fund grows date fields
510 |         dto.expires_on = None
    |

F821 Undefined name `Grant`
   --> app/slices/finance/services_grants.py:166:13
    |
165 |     # Create the Grant row
166 |     grant = Grant(
    |             ^^^^^
167 |         fund_id=fund.ulid,
168 |         sponsor_ulid=sponsor_ulid,
    |

F821 Undefined name `Grant`
   --> app/slices/finance/services_grants.py:283:28
    |
281 |         )
282 |
283 |     grant = db.session.get(Grant, grant_id)
    |                            ^^^^^
284 |     if grant is None or not grant.active:
285 |         raise LookupError(f"grant {grant_id!r} not found or inactive")
    |

F821 Undefined name `Reimbursement`
   --> app/slices/finance/services_grants.py:291:21
    |
289 |     # require non-empty strings; Governance can enforce semantics.
290 |
291 |     reimbursement = Reimbursement(
    |                     ^^^^^^^^^^^^^
292 |         grant_id=grant.ulid,
293 |         submitted_on=submitted_on,
    |

F821 Undefined name `Reimbursement`
   --> app/slices/finance/services_grants.py:390:36
    |
388 |         raise ValueError("status must be 'paid' or 'void' for mark_disbursed")
389 |
390 |     reimbursement = db.session.get(Reimbursement, reimbursement_id)
    |                                    ^^^^^^^^^^^^^
391 |     if reimbursement is None:
392 |         raise LookupError(f"reimbursement {reimbursement_id!r} not found")
    |

E741 Ambiguous variable name: `l`
   --> app/slices/finance/services_journal.py:435:12
    |
433 |     fund_codes: set[str] = set()
434 |
435 |     for i, l in enumerate(lines, start=1):
    |            ^
436 |         if not isinstance(l, dict):
437 |             raise ValueError(f"line {i} must be a dict")
    |

E741 Ambiguous variable name: `l`
   --> app/slices/finance/services_journal.py:499:14
    |
497 |     db.session.flush()  # assign j.ulid
498 |
499 |     for seq, l in enumerate(lines, start=1):
    |              ^
500 |         db.session.add(
501 |             JournalLine(
    |

E741 Ambiguous variable name: `l`
   --> app/slices/finance/services_journal.py:562:9
    |
560 |     )
561 |     lines = []
562 |     for l in orig_lines:
    |         ^
563 |         lines.append(
564 |             {
    |

E741 Ambiguous variable name: `l`
    --> app/slices/finance/services_journal.py:1060:9
     |
1058 | def _apply_to_balances(*, lines: Iterable[dict], period_key: str) -> None:
1059 |     buckets: dict[tuple[str, str, Optional[str]], int] = defaultdict(int)
1060 |     for l in lines:
     |         ^
1061 |         k = (l["account_code"], l["fund_code"], l.get("project_ulid"))
1062 |         buckets[k] += int(l["amount_cents"])
     |

E741 Ambiguous variable name: `l`
    --> app/slices/finance/services_journal.py:1125:9
     |
1123 |     )
1124 |     buckets: dict[str, list[dict]] = defaultdict(list)
1125 |     for l in lines:
     |         ^
1126 |         buckets[l.period_key].append(
1127 |             {
     |

B007 Loop control variable `k` not used within loop body
   --> app/slices/finance/services_report.py:103:9
    |
101 |         bucket["revenue_cents"] += int(r["revenue_cents"] or 0)
102 |         bucket["expense_cents"] += int(r["expense_cents"] or 0)
103 |     for k, v in by_restriction.items():
    |         ^
104 |         v["change_net_assets_cents"] = v["revenue_cents"] - v["expense_cents"]
    |
help: Rename unused `k` to `_k`

F841 Local variable `by_fund` is assigned to but never used
   --> app/slices/finance/services_report.py:106:5
    |
104 |         v["change_net_assets_cents"] = v["revenue_cents"] - v["expense_cents"]
105 |
106 |     by_fund = {
    |     ^^^^^^^
107 |         (r["fund_id"] or "-"): {
108 |             "name": r["fund_name"],
    |
help: Remove assignment to unused variable `by_fund`

F841 Local variable `by_project` is assigned to but never used
   --> app/slices/finance/services_report.py:115:5
    |
113 |         for r in fund_rows
114 |     }
115 |     by_project = {
    |     ^^^^^^^^^^
116 |         (r["project_id"] or "-"): {
117 |             "name": r["project_name"],
    |
help: Remove assignment to unused variable `by_project`

Found 70 errors (50 fixed, 20 remaining).
No fixes available (3 hidden fixes can be enabled with the `--unsafe-fixes` option).
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ ruff check app/slices/governance
F821 Undefined name `current_app`
  --> app/slices/governance/governance_routes_example_.py:17:9
   |
16 |     def _audit(evt):
17 |         current_app.logger.info("policy_audit %s", evt)
   |         ^^^^^^^^^^^
18 |
19 |     saved = save_policy(
   |

F821 Undefined name `current_app`
  --> app/slices/governance/governance_routes_example_.py:35:9
   |
34 |     def _audit(evt):
35 |         current_app.logger.info("policy_audit %s", evt)
   |         ^^^^^^^^^^^
36 |
37 |     saved = save_policy(
   |

F821 Undefined name `POLICY_REGISTRY`
   --> app/slices/governance/services.py:467:17
    |
466 |     # Trim/lower/dedupe the single array field
467 |     schema, _ = POLICY_REGISTRY[key]
    |                 ^^^^^^^^^^^^^^^
468 |     (field_name,) = schema["properties"].keys()
469 |     arr = value.get(field_name, [])
    |

F821 Undefined name `POLICY_REGISTRY`
   --> app/slices/governance/services.py:496:19
    |
494 |     """Return sorted POLICY_REGISTRY keys for discovery and UX/tests."""
495 |
496 |     return sorted(POLICY_REGISTRY.keys())
    |                   ^^^^^^^^^^^^^^^
    |

F821 Undefined name `POLICY_REGISTRY`
   --> app/slices/governance/services.py:539:33
    |
537 |     except PolicyNotFoundError:
538 |         # Bootstrap from defaults if first use
539 |         schema, default_value = POLICY_REGISTRY[family]
    |                                 ^^^^^^^^^^^^^^^
540 |         set_policy(namespace, key, default_value, actor_entity_ulid=None)
541 |         return default_value
    |

F821 Undefined name `set_policy`
   --> app/slices/governance/services.py:540:9
    |
538 |         # Bootstrap from defaults if first use
539 |         schema, default_value = POLICY_REGISTRY[family]
540 |         set_policy(namespace, key, default_value, actor_entity_ulid=None)
    |         ^^^^^^^^^^
541 |         return default_value
    |

F821 Undefined name `_policy_upsert`
   --> app/slices/governance/services.py:652:12
    |
650 |         },
651 |     }
652 |     return _policy_upsert(
    |            ^^^^^^^^^^^^^^
653 |         namespace="governance",
654 |         key="roles",
    |

F821 Undefined name `_policy_upsert`
   --> app/slices/governance/services.py:720:12
    |
718 |         "additionalProperties": False,
719 |     }
720 |     return _policy_upsert(
    |            ^^^^^^^^^^^^^^
721 |         namespace="governance",
722 |         key="offices",
    |

F821 Undefined name `_policy_upsert`
   --> app/slices/governance/services.py:784:12
    |
782 |         "additionalProperties": False,
783 |     }
784 |     return _policy_upsert(
    |            ^^^^^^^^^^^^^^
785 |         namespace="governance.spending",
786 |         key="matrix",
    |

F821 Undefined name `_policy_upsert`
   --> app/slices/governance/services.py:832:12
    |
830 |     namespace = ".".join(parts[:-1]) if len(parts) > 1 else "governance"
831 |     key = parts[-1] if parts else "policy"
832 |     return _policy_upsert(
    |            ^^^^^^^^^^^^^^
833 |         namespace=namespace,
834 |         key=key,
    |

F821 Undefined name `_policy_upsert`
   --> app/slices/governance/services.py:941:12
    |
939 |         "additionalProperties": False,
940 |     }
941 |     return _policy_upsert(
    |            ^^^^^^^^^^^^^^
942 |         namespace="governance.state_machine",
943 |         key=f"{policy_key}:{entity_kind}",
    |

Found 11 errors.
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ ruff check app/slices/ledger
All checks passed!
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ ruff check app/slices/logistics
All checks passed!
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ ruff check app/slices/resources
F821 Undefined name `EntityOrg`
   --> app/slices/resources/models.py:243:18
    |
241 |     )
242 |
243 |     org: Mapped["EntityOrg"] = relationship(
    |                  ^^^^^^^^^
244 |         "EntityOrg",
245 |         back_populates="resource_pocs",
    |

F821 Undefined name `EntityPerson`
   --> app/slices/resources/models.py:249:21
    |
247 |         passive_deletes=True,
248 |     )
249 |     person: Mapped["EntityPerson"] = relationship(
    |                     ^^^^^^^^^^^^
250 |         "EntityPerson",
251 |         passive_deletes=True,
    |

Found 3 errors (1 fixed, 2 remaining).
(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ ruff check app/slices/sponsors
F821 Undefined name `EntityOrg`
   --> app/slices/sponsors/models.py:299:18
    |
297 |     )
298 |
299 |     org: Mapped["EntityOrg"] = relationship(
    |                  ^^^^^^^^^
300 |         "EntityOrg",
301 |         back_populates="sponsor_pocs",
    |

F821 Undefined name `EntityPerson`
   --> app/slices/sponsors/models.py:304:21
    |
302 |         passive_deletes=True,
303 |     )
304 |     person: Mapped["EntityPerson"] = relationship(
    |                     ^^^^^^^^^^^^
305 |         "EntityPerson",
306 |         passive_deletes=True,
    |

Found 2 errors.



## Extensions Check

(vcdb-v2) user@zbook-17:~/Documents/App_Dev/vcdb-v2$ ruff check app/extensions
warning: Invalid rule code provided to `# noqa` at app/extensions/contracts/governance_v2.py:894: B902
B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/calendar_v2.py:156:9
    |
154 |         }
155 |     except Exception as exc:
156 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/calendar_v2.py:255:9
    |
253 |         )
254 |     except Exception as exc:
255 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/calendar_v2.py:325:9
    |
324 |     except Exception as exc:
325 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/calendar_v2.py:357:9
    |
355 |         return svc.list_funding_plans_for_project(project_ulid)
356 |     except Exception as exc:
357 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/calendar_v2.py:387:9
    |
385 |         return svc.list_projects_for_period(period_label)
386 |     except Exception as exc:  # noqa: BLE001
387 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/customers_v2.py:202:9
    |
200 |         )
201 |     except Exception as e:
202 |         raise _as_contract_error(where, e)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/customers_v2.py:280:9
    |
278 |         )
279 |     except Exception as exc:
280 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/customers_v2.py:305:9
    |
303 |         )
304 |     except Exception as exc:
305 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/customers_v2.py:330:9
    |
328 |         )
329 |     except Exception as exc:
330 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/customers_v2.py:355:9
    |
353 |         )
354 |     except Exception as exc:
355 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
  --> app/extensions/contracts/entity_v2.py:82:9
   |
80 |         )
81 |     except Exception as exc:
82 |         raise _as_contract_error(where, exc)
   |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/finance_v2.py:310:9
    |
309 |     except Exception as exc:
310 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/finance_v2.py:394:9
    |
393 |     except Exception as exc:
394 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/finance_v2.py:463:9
    |
462 |     except Exception as exc:
463 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/finance_v2.py:532:9
    |
531 |     except Exception as exc:
532 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/finance_v2.py:581:9
    |
579 |         return svc.get_fund_summary(fund_ulid)
580 |     except Exception as exc:
581 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/finance_v2.py:602:9
    |
600 |         )
601 |     except Exception as exc:
602 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/finance_v2.py:689:9
    |
688 |     except Exception as exc:
689 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/finance_v2.py:759:9
    |
758 |     except Exception as exc:
759 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/finance_v2.py:812:9
    |
811 |     except Exception as exc:
812 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/finance_v2.py:854:9
    |
853 |     except Exception as exc:
854 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/governance_v2.py:468:9
    |
466 |               return json.load(f)
467 |       except FileNotFoundError:
468 | /         raise ContractError(
469 | |             code="policy_missing",
470 | |             where=where,
471 | |             message=f"policy file missing: {path}",
472 | |             http_status=503,
473 | |             data={"path": str(path)},
474 | |         )
    | |_________^
475 |       except Exception as e:
476 |           raise ContractError(
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/governance_v2.py:476:9
    |
474 |           )
475 |       except Exception as e:
476 | /         raise ContractError(
477 | |             code="policy_read_error",
478 | |             where=where,
479 | |             message=str(e),
480 | |             http_status=503,
481 | |             data={"path": str(path)},
482 | |         )
    | |_________^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
    --> app/extensions/contracts/governance_v2.py:1305:9
     |
1303 |         )
1304 |     except Exception as exc:
1305 |         raise _as_contract_error(where, exc)
     |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
     |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
    --> app/extensions/contracts/governance_v2.py:1357:9
     |
1355 |         return out
1356 |     except Exception as exc:  # noqa: BLE001 - boundary wrapper
1357 |         raise _as_contract_error(where, exc)
     |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
     |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
    --> app/extensions/contracts/governance_v2.py:1413:9
     |
1411 |         )
1412 |     except Exception as exc:
1413 |         raise _as_contract_error(where, exc)
     |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
     |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
    --> app/extensions/contracts/governance_v2.py:1487:9
     |
1485 |         )
1486 |     except Exception as exc:
1487 |         raise _as_contract_error(where, exc)
     |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
     |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/resources_v2.py:167:9
    |
165 |         return _one("resource_ulid", rid)
166 |     except Exception as exc:
167 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/resources_v2.py:187:9
    |
185 |         return _one("version_ptr", version_ptr)
186 |     except Exception as exc:
187 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/resources_v2.py:207:9
    |
205 |         return _one("version_ptr", version_ptr)
206 |     except Exception as exc:
207 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/resources_v2.py:227:9
    |
225 |         return _one("history_ulid", hist)
226 |     except Exception as exc:
227 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/resources_v2.py:247:9
    |
245 |         return _one("history_ulid", hist)
246 |     except Exception as exc:
247 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/resources_v2.py:262:9
    |
260 |         return _one("promoted", promoted)
261 |     except Exception as exc:
262 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/resources_v2.py:277:9
    |
275 |         return _ok({"reindexed": int(n)})
276 |     except Exception as exc:
277 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/resources_v2.py:296:9
    |
294 |         )
295 |     except Exception as exc:
296 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/sponsors_v2.py:159:9
    |
157 |         return _one("sponsor_ulid", sid)
158 |     except Exception as exc:
159 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/sponsors_v2.py:186:9
    |
184 |         return _ok({"history_ulid": hist, "sponsor": view})
185 |     except Exception as exc:
186 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/sponsors_v2.py:213:9
    |
211 |         return _ok({"history_ulid": hist, "sponsor": view})
212 |     except Exception as exc:
213 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/sponsors_v2.py:238:9
    |
236 |         return _ok({"pledge_ulid": pid, "sponsor": view})
237 |     except Exception as exc:
238 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/sponsors_v2.py:261:9
    |
259 |         return _ok({})
260 |     except Exception as exc:
261 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/sponsors_v2.py:357:9
    |
355 |         return _ok(result)
356 |     except Exception as exc:
357 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/sponsors_v2.py:369:9
    |
367 |         return _ok(view)
368 |     except Exception as exc:
369 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/contracts/sponsors_v2.py:456:9
    |
454 |         return _ok(result)
455 |     except Exception as exc:
456 |         raise _as_contract_error(where, exc)
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
  --> app/extensions/contracts/validate.py:53:9
   |
51 |         Draft202012Validator(schema).validate(payload)
52 |     except JSONSchemaValidationError as e:
53 |         raise ContractValidationError.from_jsonschema(e)
   |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
   |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/policy_semantics.py:259:9
    |
257 |           staff_cap_int = int(staff_cap)
258 |       except Exception as e:
259 | /         raise PolicyError(
260 | |             f"finance_controls.spending.staff_cap_cents must be an int: {e}"
261 | |         )
    | |_________^
262 |       if staff_cap_int < 0:
263 |           raise PolicyError(
    |

B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
   --> app/extensions/policy_semantics.py:338:9
    |
336 |         period = int(cad.get("period_days", 365))
337 |     except Exception as e:
338 |         raise PolicyError(f"{where}: cadence fields must be ints: {e}")
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
339 |     if max_per < 1:
340 |         raise PolicyError(f"{where}: cadence.max_per_period must be >= 1")
    |

Found 54 errors (8 fixed, 46 remaining).
