### Architecture Uniformity — Enforcement Checklist

Use this checklist during refactors and code review. If an item fails, the change is not canon-compliant.

#### Boundaries & Imports

- [ ] No slice imports another slice (directly or indirectly). Cross-slice calls go through **extensions/contracts** only.
- [ ] `app/lib/*` does not import any slice code. Slices may import `app.lib.*`, never the reverse.
- [ ] No ORM models cross slice boundaries (only DTOs/primitive types cross contracts).

#### Transactions & Side Effects

- [ ] Services are **flush-only** (no `commit()` / `rollback()` anywhere in `services/*`).
- [ ] Routes/CLI own transaction scope, db.session,`commit/rollback` and error boundaries (single consistent transaction pattern per request).
- [ ] Ledger/event emits occur only at the approved layer (per current canon: route or explicitly designated command service), and never include PII.

#### Mapper Layer

- [ ] Slice has `app/slices/<slice>/mapper.py` and it contains projection logic + typed view/DTO shapes.
- [ ] Mappers do not run DB queries or cause side effects (no writes, no commits, no emits).
- [ ] Services call mappers; contracts return mapper/DTO shapes; routes never serialize ORM objects directly.

#### Naming & Identity

- [ ] Identity is always `entity_ulid` (facet PK=FK). No “slice ULID” used as an identity anchor.
- [ ] Function signatures use explicit names (`entity_ulid`, `request_id`, `actor_ulid`) and avoid ambiguous variables like `ent` for multiple meanings.

#### PII Discipline

- [ ] No PII outside the Entity slice (except approved snapshot stores). No PII in logs/Ledger.
- [ ] Entity mappers/projectors return only the minimum allowed display/contact fields for the caller’s need (least-privilege).

#### Pagination & Shapes

- [ ] Paginated reads use the shared pagination primitive (`Page` / `paginate_sa`) and return a consistent page shape.
- [ ] Query functions return typed view/DTO shapes (TypedDict/dataclass DTO), not raw dicts or ORM objects.

#### “Before Adding Code”

- [ ] If you need a generic helper: check `app/lib` first; if it’s generic + non-PII, put it there.
- [ ] If you need a projection: put it in the slice’s `mapper.py`.
- [ ] If you need business logic: put it in `services/*` (queries vs commands), not in contracts/routes.
