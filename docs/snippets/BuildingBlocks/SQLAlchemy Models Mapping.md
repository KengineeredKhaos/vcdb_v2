# SQLAlchemy Models Mapping

I read your `/mnt/data/dev.db.sql` and pulled the tables it defines (highlights below), then sketched idiomatic Flask-SQLAlchemy models that match it exactly (types, PKs/FKs, uniques), plus a couple of pragmatic conveniences for JSON columns.

---

# What’s in the schema (quick map)

- **Governance**
  
  - `governance_policy` (key, value_json, schema_json, created/updated)
  
  - `governance_office`, `governance_officer_term`, `governance_authorization`

- **Entity**
  
  - `entity_entity` (id ULID(26), kind, created/updated)
  
  - `entity_person` (1:1 onto entity_entity)
  
  - `entity_org` (1:1 onto entity_entity)
  
  - `entity_contact` (N:1 to entity_entity)
  
  - `entity_address` (N:1 to entity_entity)
  
  - `entity_role` (entity_id, role, assigned_by, assigned_at…)

- **Auth (RBAC)**
  
  - `users` (id ULID(26), email unique, password_hash, is_active, created/updated)
  
  - `roles` (id ULID(26), name unique)
  
  - `user_roles` (user_id, role_id unique pair)

- **Ledger**
  
  - `transactions_ledger` (id ULID, type, domain, operation, happened_at_utc, request_id unique, … hash fields)

- **Admin/Infra**
  
  - `cron_status` (job_key unique, last_run_at_utc, state)

- **Resources (inventory skeleton)**
  
  - `resources_location`, `resources_resource`, `resources_assignment`

---

## ULIDPK Primary Key & Foreign Keys

Locked in. Sticking with **`ulid`** as every table’s PK is a great fit for your contracts/ledger and makes forensic timelines trivial.

Here’s a tight checklist + drop-ins so it’s consistent everywhere:

### 1) PK mixin (final form)

```python
# app/lib/models.py
from sqlalchemy import String, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.lib.ids import new_ulid

class ULIDPK:
    ulid: Mapped[str] = mapped_column(
        String(26),
        primary_key=True,
        nullable=False,
        default=new_ulid,
    )
    __table_args__ = (
        CheckConstraint("length(ulid) = 26", name="ck_ulid_len_26"),
    )
```

### Optional stricter CHECK (SQLite-safe)

SQLite has no regex, but you can enforce base32 chars with `GLOB`:

```sql
CHECK (ulid GLOB '[0-9A-HJKMNP-TV-Z][0-9A-HJKMNP-TV-Z]*' AND length(ulid)=26)
```

(You can add this via Alembic if you want stronger guarantees.)

### 2) FK pattern (readable & indexed)

```python
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

class Resource(db.Model, ULIDPK):
    __tablename__ = "resource_resource"

    entity_ulid: Mapped[str] = mapped_column(
        String(26),
        ForeignKey("entity_entity.ulid", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    entity = relationship("Entity", foreign_keys=[entity_ulid], backref="resources")
```

- Always name FKs `*_ulid`.

- Always `index=True` on high-traffic FKs.

### 3) Query ergonomics

- Creation-order: `ORDER BY ulid` (ULIDs are k-sortable).

- For “since timestamp” queries, either:
  
  - use a created_at column (if you add one), or
  
  - provide a helper to compute the **minimum ULID for a given UTC time** and `WHERE ulid >= that_ulid`.

If you don’t already have it, I can add a tiny helper in `lib/ids.py` like `ulid_min_for(dt)` to generate that boundary ULID.

### 4) Migrations (if any tables currently use `id`)

Alembic outline to rename + backfill:

1. `op.add_column('table', sa.Column('ulid', sa.String(26), nullable=True))`

2. Backfill rows with `new_ulid()` (server default or Python loop).

3. `op.create_check_constraint('ck_ulid_len_26', 'table', 'length(ulid)=26')`

4. Drop old PK, make `ulid` PK, drop old `id`.

5. Update FKs in dependent tables to point to `.ulid`.

### 5) App-wide conventions (pin these)

- PK column name is **always** `ulid`.

- All FKs end with `_ulid`.

- DTO/contract fields mirror DB names (`entity_ulid`, `resource_ulid`, `event_ulid`, …).

- Services/ledger use `ulid` consistently—no `id`/`ulid` translation layers.

---

##ULIDPK Modeling patterns (drop-in snippets)

Below I show the **exact** column names and types to match your SQL. I’m using `db.String(26)` for ULIDs (you can later swap for a shared `ULIDPK` if you expose one in `app.lib`).

Where you have `*_json` TEXT columns, I add a small **hybrid property** pair (`@property` + `@<name>.setter`) so your services can use dicts/lists while the DB stores JSON strings.

> Replace `from app.extensions import db` with your real import path.

## Governance — `governance_policy`

```python
from __future__ import annotations
from datetime import datetime
import json
from flask_sqlalchemy import SQLAlchemy

db: SQLAlchemy  # provided by your extensions

class GovernancePolicy(db.Model):
    __tablename__ = "governance_policy"

    key = db.Column(db.String(80), primary_key=True)
    value_json = db.Column(db.Text, nullable=False)
    schema_json = db.Column(db.Text, nullable=True)
    created_at_utc = db.Column(db.DateTime, nullable=False)
    updated_at_utc = db.Column(db.DateTime, nullable=False)

    # Convenience accessors
    @property
    def value(self) -> dict:
        return {} if not self.value_json else json.loads(self.value_json)

    @value.setter
    def value(self, obj: dict) -> None:
        self.value_json = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

    @property
    def schema(self) -> dict | None:
        return None if not self.schema_json else json.loads(self.schema_json)

    @schema.setter
    def schema(self, obj: dict | None) -> None:
        self.schema_json = None if obj is None else json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
```

## What the JSON helpers are for (and why they matter)

In this project we use JSON in three places:

1. **Persistence / columns** (e.g., `policy.value_json`, `ledger.changed_fields_json`)

2. **Wire/contract payloads** (Extensions DTOs)

3. **Hashing/audit** (stable, repeatable JSON for ledger hashes)

Typical helpers you’ll see (names may vary):

- `json_dumps_canonical(obj) -> str`  
  Stable, UTF-8 JSON with:
  
  - sorted keys (so the same data → same bytes)
  
  - no NaN, no trailing spaces
  
  - datetime → ISO-8601 Zulu
  
  - Decimal → string/float (your call)  
    Why: stable bytes let you compute a repeatable `event_hash`.

- `json_loads_safe(s: str) -> Any`  
  Strict load that refuses duplicate keys, invalid numbers, etc.  
  Why: prevents garbage from entering the system.

- `strip_nones(obj) -> obj` (optional)  
  Removes `None` fields before serialization for cleaner payloads.

- `coerce_to_jsonable(obj) -> obj`  
  Converts objects (ULIDs, datetimes, UUIDs, Enums) into JSON-friendly forms.

- `validate_against_schema(data, schema)`  
  JsonSchema validation in one line; raise your `ContractValidationError` on failure.

In short: **helpers give you safe, canonical JSON** that (a) validates, (b) won’t break round-trips, and (c) produces identical bytes for hashing/audit.

## Entity core

Absolutely—here’s a cleaned, production-ready `app/slices/entity/models.py` that matches your helpers and the “ulid everywhere” rule, plus notes on pitfalls to avoid.

```python
# app/slices/entity/models.py
from __future__ import annotations

from sqlalchemy import String, UniqueConstraint, CheckConstraint, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.lib.chrono import utc_now
from app.lib.models import ULIDPK, ULIDFK


# -------------------------
# Core "Entity"
# -------------------------
class Entity(db.Model, ULIDPK):
    __tablename__ = "entity_entity"

    # PK 'ulid' comes from ULIDPK (String(26), default=new_ulid)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    created_at_utc: Mapped[str] = mapped_column(String(30), default=utc_now, nullable=False)
    updated_at_utc: Mapped[str] = mapped_column(String(30), default=utc_now, onupdate=utc_now, nullable=False)

    # One-to-ones
    person: Mapped["EntityPerson"] = relationship("EntityPerson", back_populates="entity", uselist=False)
    org: Mapped["EntityOrg"] = relationship("EntityOrg", back_populates="entity", uselist=False)

    # One-to-many
    roles: Mapped[list["EntityRole"]] = relationship(
        "EntityRole", back_populates="entity", cascade="all, delete-orphan"
    )
    contacts: Mapped[list["EntityContact"]] = relationship(
        "EntityContact", back_populates="entity", cascade="all, delete-orphan"
    )
    addresses: Mapped[list["EntityAddress"]] = relationship(
        "EntityAddress", back_populates="entity", cascade="all, delete-orphan"
    )


# -------------------------
# Entity Person (1:1 with Entity)
# -------------------------
class EntityPerson(db.Model, ULIDPK):
    __tablename__ = "entity_person"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity")
    entity: Mapped[Entity] = relationship("Entity", back_populates="person")

    first_name: Mapped[str] = mapped_column(String(40), nullable=False)
    last_name: Mapped[str] = mapped_column(String(60), nullable=False)
    preferred_name: Mapped[str | None] = mapped_column(String(60), nullable=True)

    created_at_utc: Mapped[str] = mapped_column(String(30), default=utc_now, nullable=False)
    updated_at_utc: Mapped[str] = mapped_column(String(30), default=utc_now, onupdate=utc_now, nullable=False)

    # enforce 1:1 with Entity
    __table_args__ = (
        UniqueConstraint("entity_ulid", name="uq_person_entity"),
    )


# -------------------------
# Entity Organization (1:1 with Entity)
# -------------------------
class EntityOrg(db.Model, ULIDPK):
    __tablename__ = "entity_org"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity")
    entity: Mapped[Entity] = relationship("Entity", back_populates="org")

    legal_name: Mapped[str] = mapped_column(String(120), nullable=False)
    dba_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ein: Mapped[str | None] = mapped_column(String(9), nullable=True)  # normalized/validated in service

    created_at_utc: Mapped[str] = mapped_column(String(30), default=utc_now, nullable=False)
    updated_at_utc: Mapped[str] = mapped_column(String(30), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("entity_ulid", name="uq_org_entity"),  # enforce 1:1
    )


# -------------------------
# Entity Role (N:1 with Entity)
# -------------------------
class EntityRole(db.Model, ULIDPK):
    __tablename__ = "entity_role"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity")
    entity: Mapped[Entity] = relationship("Entity", back_populates="roles")

    role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    created_at_utc: Mapped[str] = mapped_column(String(30), default=utc_now, nullable=False)
    updated_at_utc: Mapped[str] = mapped_column(String(30), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        # Governance enforces allowed values; DB enforces uniqueness per entity
        UniqueConstraint("entity_ulid", "role", name="uq_entity_role_pair"),
    )


# -------------------------
# Entity Contact (N:1 with Entity)
# -------------------------
class EntityContact(db.Model, ULIDPK):
    __tablename__ = "entity_contact"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity")
    entity: Mapped[Entity] = relationship("Entity", back_populates="contacts")

    email: Mapped[str | None] = mapped_column(String(254), nullable=True)     # normalized/validated in service
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)      # normalized/validated in service
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at_utc: Mapped[str] = mapped_column(String(30), default=utc_now, nullable=False)
    updated_at_utc: Mapped[str] = mapped_column(String(30), default=utc_now, onupdate=utc_now, nullable=False)


# -------------------------
# Entity Address (N:1 with Entity)
# -------------------------
class EntityAddress(db.Model, ULIDPK):
    __tablename__ = "entity_address"

    entity_ulid: Mapped[str] = ULIDFK("entity_entity")
    entity: Mapped[Entity] = relationship("Entity", back_populates="addresses")

    is_physical: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_postal: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    address1: Mapped[str] = mapped_column(String(80), nullable=False)
    address2: Mapped[str | None] = mapped_column(String(80), nullable=True)
    city: Mapped[str] = mapped_column(String(60), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)   # two-letter code; validate in service
    postal_code: Mapped[str] = mapped_column(String(10), nullable=False)

    created_at_utc: Mapped[str] = mapped_column(String(30), default=utc_now, nullable=False)
    updated_at_utc: Mapped[str] = mapped_column(String(30), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        CheckConstraint("length(state) = 2", name="ck_state_len_2"),
    )


__all__ = [
    "Entity",
    "EntityPerson",
    "EntityOrg",
    "EntityRole",
    "EntityContact",
    "EntityAddress",
]
```

### Why this layout

- **ULIDPK + ULIDFK** are used exactly as intended—no extra PK column declarations needed.

- **Timestamps** call your canonical `utc_now()` (returns ISO-8601 “Z” strings) for `default` and `onupdate`—no `.isoformat()` needed.

- **One-to-one** (Person/Org) is enforced with a `UniqueConstraint` on `entity_ulid`.

- **One-to-many** (Roles/Contacts/Addresses) use `cascade="all, delete-orphan"` so children don’t dangle.

- **Validation** of emails/phones/EIN/state is **kept in services** using your normalizers/validators, not DB triggers (cleaner and testable). See `app/lib/utils.py` and `app/lib/geo.py`.

### Traps to avoid (you had a couple in the draft)

- **Don’t subclass `ULIDFK`.** It’s a column factory, not a mixin—use it to define `*_ulid` fields (as above).

- **Don’t double-format timestamps.** `utc_now()` already returns a string like `2025-10-11T08:59:00.123Z`. Passing `default=utc_now` is correct; calling `.isoformat()` on that would error.

- **Spelling matters in FKs.** Point FKs to `"entity_entity.ulid"` (table `__tablename__` + `.ulid`). A prior draft had typos; using `ULIDFK("entity_entity")` prevents that class of mistakes.

- **Don’t mix PK strategies.** You’ve “slapped the table” on ULID as the sole PK. Keep it consistent—use unique constraints for natural keys instead of composite PKs.

### Where validations live (recommended)

- **Email/phone/EIN:** normalize/validate in the **entity service** using `normalize_email`, `assert_valid_email`, `normalize_phone`, `assert_valid_phone`, `normalize_ein`, `validate_ein`.

- **State codes:** normalize/validate with `geo.normalize_state` / `geo.is_state_code` before write; keep DB checks coarse (length == 2) to stay SQLite-portable.

If you want, I can also hand you tiny unit tests that assert:

- ULIDs auto-populate on insert,

- 1:1 uniqueness on `EntityPerson` / `EntityOrg`,

- and that `utc_now()` is millisecond-precision and Z-suffixed.

Absolutely—let’s wire your existing `app/slices/entity/services.py` to the **new models** you just settled on (ULID everywhere; child tables keyed by `entity_ulid`). Below is a **drop-in replacement** that:

- uses the new model names/columns (`Entity`, `EntityPerson`, `EntityOrg`, `EntityRole`, `EntityContact`, `EntityAddress`),

- uses `ulid`/`entity_ulid` consistently,

- keeps your event bus + UTC timestamps,

- preserves your normalization/validation flow (you can later move those helpers from `lib/utils.py` into this slice’s services).

---

## Example Implementation of Entity Dbase Model

```python
# app/slices/entity/services.py
from __future__ import annotations

from typing import Optional, Tuple, List

from sqlalchemy import asc
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import (
    allowed_role_codes,
    db,
    event_bus,
)
from app.lib.chrono import utc_now
from app.lib.ids import new_ulid
from app.lib.utils import (
    normalize_ein,
    normalize_email,
    normalize_phone,
    validate_ein,
    validate_email,
    validate_phone,
)

from .models import (
    Entity,
    EntityPerson,
    EntityOrg,
    EntityRole,
    EntityContact,
    EntityAddress,
)


# -----------------
# Internal guard
# -----------------
def _ensure_reqid(request_id: Optional[str]) -> str:
    if request_id is None or not str(request_id).strip():
        raise ValueError("request_id must be non-empty")
    return str(request_id)


# -----------------
# DTO mappers (read shape for templates/contracts)
# -----------------
def _person_to_dto(p: EntityPerson) -> dict:
    ent = p.entity
    # We keep a SINGLE primary EntityContact row (is_primary=True);
    # it may carry email and/or phone (both in same row)
    primary_contact = None
    if ent and ent.contacts:
        primary_contact = next((c for c in ent.contacts if c.is_primary), None)
    return {
        "entity_ulid": ent.ulid if ent else None,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "preferred_name": p.preferred_name,
        "email": primary_contact.email if primary_contact else None,
        "phone": primary_contact.phone if primary_contact else None,
        "created_at_utc": ent.created_at_utc if ent else None,
        "updated_at_utc": ent.updated_at_utc if ent else None,
    }


def _org_to_dto(o: EntityOrg) -> dict:
    ent = o.entity
    primary_contact = None
    if ent and ent.contacts:
        primary_contact = next((c for c in ent.contacts if c.is_primary), None)
    return {
        "entity_ulid": ent.ulid if ent else None,
        "kind": "org",
        "legal_name": o.legal_name,
        "dba_name": o.dba_name,
        "ein": o.ein,
        "email": primary_contact.email if primary_contact else None,
        "phone": primary_contact.phone if primary_contact else None,
        "created_at_utc": ent.created_at_utc if ent else None,
        "updated_at_utc": ent.updated_at_utc if ent else None,
    }


# -----------------
# Entity as Person
# -----------------
def ensure_person(
    *,
    first_name: str,
    last_name: str,
    email: Optional[str],
    phone: Optional[str],
    request_id: str,
    actor_id: Optional[str],
) -> str:
    """
    Idempotently ensure an 'Entity(kind=person)' exists with a Person row.
    If email/phone are provided, upsert them as the single primary contact record.
    Returns entity_ulid.
    """
    _ensure_reqid(request_id)
    fn, ln = (first_name or "").strip(), (last_name or "").strip()
    if not fn or not ln:
        raise ValueError("first_name and last_name are required")

    email_norm = normalize_email(email) if email else None
    if email is not None and email_norm and not validate_email(email_norm):
        raise ValueError("Invalid email")
    phone_norm = normalize_phone(phone) if phone else None
    if phone is not None and phone_norm and not validate_phone(phone_norm):
        raise ValueError("Invalid phone")

    # Try to find an existing person by primary contact (email first, then phone)
    ent: Entity | None = None
    if email_norm:
        ent = (
            db.session.query(Entity)
            .join(EntityContact, EntityContact.entity_ulid == Entity.ulid)
            .filter(
                Entity.kind == "person",
                EntityContact.is_primary.is_(True),
                EntityContact.email == email_norm,
            )
            .first()
        )
    if not ent and phone_norm:
        ent = (
            db.session.query(Entity)
            .join(EntityContact, EntityContact.entity_ulid == Entity.ulid)
            .filter(
                Entity.kind == "person",
                EntityContact.is_primary.is_(True),
                EntityContact.phone == phone_norm,
            )
            .first()
        )

    created = False
    if not ent:
        ent = Entity(kind="person")  # ulid auto-filled via ULIDPK.default
        db.session.add(ent)
        db.session.flush()  # so ent.ulid is available
        db.session.add(EntityPerson(entity_ulid=ent.ulid, first_name=fn, last_name=ln))
        created = True
    else:
        p = ent.person
        if p:
            p.first_name = fn or p.first_name
            p.last_name = ln or p.last_name
        else:
            db.session.add(EntityPerson(entity_ulid=ent.ulid, first_name=fn, last_name=ln))

    db.session.commit()

    # Upsert a single *primary* contact row
    if email is not None or phone is not None:
        _upsert_primary_contact(
            entity_ulid=ent.ulid, email=email_norm, phone=phone_norm
        )
        db.session.commit()

    event_bus.emit(
        type="entity.person.created" if created else "entity.person.upserted",
        slice="entity",
        operation="insert" if created else "update",
        actor_id=actor_id,
        target_id=ent.ulid,
        request_id=request_id,
        happened_at=utc_now(),
        changed_fields={
            "first_name": fn,
            "last_name": ln,
            "email": email_norm,
            "phone": phone_norm,
        },
    )
    return ent.ulid


# -----------------
# Entity as Organization
# -----------------
def ensure_org(
    *,
    legal_name: str,
    dba_name: Optional[str] = None,
    ein: Optional[str] = None,
    request_id: str,
    actor_id: Optional[str],
) -> str:
    """
    Create/update an organization entity.
    Idempotent on EIN if provided (normalized to 9 digits).
    Returns entity_ulid.
    """
    _ensure_reqid(request_id)
    ln = (legal_name or "").strip()
    if not ln:
        raise ValueError("legal_name is required")

    ent: Entity | None = None
    ein_norm = normalize_ein(ein) if ein else None
    if ein is not None and ein_norm and not validate_ein(ein_norm):
        raise ValueError("Invalid EIN (must be 9 digits)")

    if ein_norm:
        ent = (
            db.session.query(Entity)
            .join(EntityOrg, EntityOrg.entity_ulid == Entity.ulid)
            .filter(Entity.kind == "org", EntityOrg.ein == ein_norm)
            .first()
        )

    created = False
    if not ent:
        ent = Entity(kind="org")
        db.session.add(ent)
        db.session.flush()
        db.session.add(
            EntityOrg(
                entity_ulid=ent.ulid,
                legal_name=ln,
                dba_name=dba_name or None,
                ein=ein_norm,
            )
        )
        created = True
    else:
        o = ent.org
        if o:
            o.legal_name = ln or o.legal_name
            if dba_name is not None:
                o.dba_name = dba_name or None
            if ein is not None:
                o.ein = ein_norm
        else:
            db.session.add(
                EntityOrg(
                    entity_ulid=ent.ulid,
                    legal_name=ln,
                    dba_name=dba_name or None,
                    ein=ein_norm,
                )
            )

    db.session.commit()

    event_bus.emit(
        type="entity.org.created" if created else "entity.org.upserted",
        slice="entity",
        operation="insert" if created else "update",
        actor_id=actor_id,
        target_id=ent.ulid,
        request_id=request_id,
        happened_at=utc_now(),
        changed_fields={
            "legal_name": ln,
            "dba_name": dba_name,
            "ein": ein_norm,
        },
    )
    return ent.ulid


# -----------------
# Entity Contact (single primary record with email/phone fields)
# -----------------
def upsert_contacts(
    *,
    entity_ulid: str,
    email: Optional[str],
    phone: Optional[str],
    request_id: str,
    actor_id: Optional[str],
) -> None:
    """Upsert the single primary contact row for an entity; emits one event."""
    _ensure_reqid(request_id)

    ent = db.session.get(Entity, entity_ulid)
    if not ent:
        raise ValueError("entity not found")

    em = normalize_email(email) if email is not None else None
    if email is not None and em and not validate_email(em):
        raise ValueError("Invalid email")

    ph = normalize_phone(phone) if phone is not None else None
    if phone is not None and ph and not validate_phone(ph):
        raise ValueError("Invalid phone")

    changed = {}
    _upsert_primary_contact(entity_ulid=entity_ulid, email=em, phone=ph)
    if email is not None:
        changed["email"] = em
    if phone is not None:
        changed["phone"] = ph

    db.session.commit()
    if changed:
        event_bus.emit(
            type="entity.contact.upserted",
            slice="entity",
            operation="upsert",
            actor_id=actor_id,
            target_id=entity_ulid,
            request_id=request_id,
            happened_at=utc_now(),
            changed_fields=changed,
        )


# -----------------
# Entity Address
# -----------------
def upsert_address(
    *,
    entity_ulid: str,
    is_physical: bool = True,
    is_postal: bool = False,
    address1: str = "",
    address2: Optional[str] = None,
    city: str = "",
    state: str = "",
    postal_code: str = "",
    request_id: str,
    actor_id: Optional[str],
) -> str:
    """
    Create/update the single 'primary' address by (is_physical, is_postal) flags.
    Returns the address ulid.
    """
    _ensure_reqid(request_id)
    ent = db.session.get(Entity, entity_ulid)
    if not ent:
        raise ValueError("entity not found")

    def _norm(s: Optional[str]) -> Optional[str]:
        return (s or "").strip() or None

    addr = (
        db.session.query(EntityAddress)
        .filter_by(
            entity_ulid=entity_ulid,
            is_physical=is_physical,
            is_postal=is_postal,
        )
        .first()
    )

    created = False
    if not addr:
        addr = EntityAddress(
            entity_ulid=entity_ulid,
            is_physical=is_physical,
            is_postal=is_postal,
            address1=_norm(address1) or "",
            address2=_norm(address2),
            city=_norm(city) or "",
            state=_norm(state) or "",
            postal_code=_norm(postal_code) or "",
        )
        db.session.add(addr)
        created = True
    else:
        addr.address1 = _norm(address1) or addr.address1
        addr.address2 = _norm(address2)
        addr.city = _norm(city) or addr.city
        addr.state = _norm(state) or addr.state
        addr.postal_code = _norm(postal_code) or addr.postal_code

    db.session.commit()

    event_bus.emit(
        type="entity.address.upserted",
        slice="entity",
        operation="insert" if created else "update",
        actor_id=actor_id,
        target_id=entity_ulid,
        request_id=request_id,
        happened_at=utc_now(),
        changed_fields={
            "is_physical": is_physical,
            "is_postal": is_postal,
            "postal_code": addr.postal_code,
        },
        refs={"address_ulid": addr.ulid},
    )
    return addr.ulid


# -----------------
# Entity Role Codes
# -----------------
def ensure_role(
    *,
    entity_ulid: str,
    role: str,
    request_id: str,
    actor_id: Optional[str] | None,
) -> bool:
    """
    Attach a role to an entity if allowed by Governance and not already attached.
    """
    _ensure_reqid(request_id)

    allowed = set(allowed_role_codes())  # e.g., ('customer','resource','sponsor','staff','admin')
    if role not in allowed:
        raise ValueError(f"Role '{role}' not allowed by policy")

    existing = (
        db.session.query(EntityRole)
        .filter_by(entity_ulid=entity_ulid, role=role)
        .first()
    )
    if existing:
        return False  # idempotent: already has role

    rr = EntityRole(entity_ulid=entity_ulid, role=role)
    db.session.add(rr)
    db.session.commit()

    event_bus.emit(
        type="entity.role.attached",
        slice="entity",
        operation="attached",
        actor_id=actor_id,
        target_id=entity_ulid,
        request_id=request_id,
        happened_at=utc_now(),
        refs={"role": role},
    )
    return True


def remove_role(
    *,
    entity_ulid: str,
    role: str,
    request_id: str,
    actor_id: Optional[str] | None,
) -> bool:
    """
    Remove a role from an entity (idempotent).
    """
    _ensure_reqid(request_id)

    allowed = set(allowed_role_codes())
    if role not in allowed:
        raise ValueError(f"Role '{role}' not allowed by policy")

    existing = (
        db.session.query(EntityRole)
        .filter_by(entity_ulid=entity_ulid, role=role)
        .first()
    )
    if not existing:
        return False

    db.session.delete(existing)
    db.session.commit()

    event_bus.emit(
        type="entity.role.removed",
        slice="entity",
        operation="removed",
        actor_id=actor_id,
        target_id=entity_ulid,
        request_id=request_id,
        happened_at=utc_now(),
        refs={"role": role},
    )
    return True


# -----------------
# Views / listings
# -----------------
def person_view(person_ulid: str) -> Optional[dict]:
    p = db.session.get(EntityPerson, person_ulid)
    if not p:
        return None
    # eager-load primary contact for DTO
    _ = p.entity and p.entity.contacts  # touch relationship
    return _person_to_dto(p)


def list_people_with_role(role: str, page: int, per: int) -> Tuple[List[dict], int]:
    page = max(int(page or 1), 1)
    per = min(max(int(per or 20), 1), 100)

    q = (
        db.session.query(EntityPerson)
        .join(Entity, EntityPerson.entity_ulid == Entity.ulid)
        .join(EntityRole, EntityRole.entity_ulid == Entity.ulid)
        .filter(EntityRole.role == role)
        .options(
            joinedload(EntityPerson.entity).options(
                selectinload(Entity.contacts), selectinload(Entity.roles)
            )
        )
        .order_by(
            asc(EntityPerson.last_name),
            asc(EntityPerson.first_name),
            asc(Entity.ulid),
        )
    )
    total = q.count()
    if total == 0:
        return [], 0

    rows = q.offset((page - 1) * per).limit(per).all()
    return [_person_to_dto(p) for p in rows], total


def list_orgs_with_role(role: str, page: int, per: int) -> Tuple[List[dict], int]:
    page = max(int(page or 1), 1)
    per = min(max(int(per or 20), 1), 100)

    q = (
        db.session.query(EntityOrg)
        .join(Entity, EntityOrg.entity_ulid == Entity.ulid)
        .join(EntityRole, EntityRole.entity_ulid == Entity.ulid)
        .filter(EntityRole.role == role)
        .options(
            joinedload(EntityOrg.entity).options(
                selectinload(Entity.contacts), selectinload(Entity.roles)
            )
        )
        .order_by(asc(EntityOrg.legal_name), asc(Entity.ulid))
    )
    total = q.count()
    if total == 0:
        return [], 0

    rows = q.offset((page - 1) * per).limit(per).all()
    return [_org_to_dto(o) for o in rows], total


# -----------------
# Internals
# -----------------
def _upsert_primary_contact(
    *, entity_ulid: str, email: Optional[str], phone: Optional[str]
) -> None:
    """
    Maintain exactly one primary EntityContact row per entity.
    - If no row exists, create one with provided fields (could be email, phone or both).
    - If row exists, update only fields that are not None.
    - If a provided field is explicitly None, clear that field (treat as removal).
    """
    c = (
        db.session.query(EntityContact)
        .filter_by(entity_ulid=entity_ulid, is_primary=True)
        .first()
    )
    if not c:
        c = EntityContact(entity_ulid=entity_ulid, is_primary=True)
        if email is not None:
            c.email = email
        if phone is not None:
            c.phone = phone
        db.session.add(c)
        return

    # Update in-place
    if email is not None:
        c.email = email
    if phone is not None:
        c.phone = phone
```

---

## Notes & “trap” call-outs

- **Use `entity_ulid`, not `entity_id`:** all FKs are `*_ulid`. The services above join/filter using `Entity.ulid` consistently.

- **Primary contact = one row:** the new model carries `email` and `phone` on the same row (`EntityContact`) with `is_primary=True`. That means you don’t need separate “kind/value” rows anymore. `_upsert_primary_contact` keeps exactly **one** primary record.

- **No `.isoformat()` on timestamps:** `utc_now()` already returns an ISO-8601 Z string. Pass it straight into `event_bus.emit(happened_at=utc_now())`.

- **Idempotency:** `ensure_role`, `remove_role`, `ensure_person`/`ensure_org` are idempotent where it makes sense; repeated calls won’t duplicate roles or explode on missing rows.

- **Validation migration:** you said you’ll move email/phone/EIN validation into this slice—great. The current imports from `app.lib.utils` will keep you running until you relocate those helpers.

If you want, I can also generate a tiny Alembic migration checklist to rename any lingering `entity_id` columns → `entity_ulid` and to add the `uq_entity_role_pair` unique constraint, but the services above will work with the **models you just pinned**.

## Auth (RBAC)

```python
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.String(26), primary_key=True)  # ULID
    email = db.Column(db.String
```

---

## SQLAlchemy patterns you’ll likely want (w/ indexes, constraints, etc.)

Below are compact, copy-pasteable examples. They use SQLAlchemy 2.0 style typing.

## 1) Common mixins

```python
# app/lib/models.py (or similar)
from datetime import datetime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, DateTime, func
from app.lib.ids import ulid_str  # your helper

class Base(DeclarativeBase):
    pass

class ULIDPK:
    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=ulid_str)

class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )
```

## 2) Basic model with unique & functional indexes

```python
from sqlalchemy import String, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, validates

class Account(ULIDPK, Timestamped, Base):
    __tablename__ = "account"

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("email", name="uq_account_email"),
        # Functional index (SQLite): create an index on lower(email)
        Index("ix_account_email_lower", text("lower(email)")),
    )

    @validates("email")
    def _validate_email(self, _, v: str) -> str:
        # hook your app.lib.utils.normalize_email here
        return v.strip().lower()
```

> **Notes**
> 
> - In SQLite, functional indexes work if you use `text("lower(email)")`.
> 
> - For Postgres you’d write `Index("ix_account_email_lower", func.lower(Account.email))`.

## 3) Many-to-many through association table (with uniqueness)

```python
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

class Role(ULIDPK, Timestamped, Base):
    __tablename__ = "rbac_role"
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

class AccountRole(Base):
    __tablename__ = "account_rbac_role"
    account_id: Mapped[str] = mapped_column(ForeignKey("account.id"), primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("rbac_role.id"), primary_key=True)
    __table_args__ = (
        UniqueConstraint("account_id", "role_id", name="uq_account_role"),
    )

Account.roles = relationship(
    Role,
    secondary="account_rbac_role",
    backref="accounts",
    lazy="selectin",
)
```

## 4) JSON column (SQLite)

SQLite stores JSON as TEXT; SQLAlchemy’s `JSON` type uses TEXT under the hood and can give you dict/list transparently.

```python
from sqlalchemy import JSON

class Policy(ULIDPK, Timestamped, Base):
    __tablename__ = "policy"
    key: Mapped[str]  = mapped_column(String(128), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)  # JSON payload
```

If you need **canonical bytes for hashing**, store **both**:

- `value` (JSON/dict) for convenient reads/writes

- `value_canon` (TEXT) that keeps `json_dumps_canonical(value)` for audit/hashes

```python
from sqlalchemy import Text

class Policy(ULIDPK, Timestamped, Base):
    __tablename__ = "policy"
    key: Mapped[str]  = mapped_column(String(128), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    value_canon: Mapped[str] = mapped_column(Text, nullable=False)

    @staticmethod
    def from_payload(key: str, payload: dict) -> "Policy":
        from app.lib.jsonutil import json_dumps_canonical
        return Policy(key=key, value=payload, value_canon=json_dumps_canonical(payload))
```

## 5) Partial index (SQLite ≥ 3.8.0)

```python
from sqlalchemy import Index, text

# Only index active accounts (example)
Index(
    "ix_account_active_email",
    text("lower(email)"),
    sqlite_where=text("is_active = 1"),
    unique=False,
    table=Account.__table__,
)
```

> Attach after model definition or inside `__table_args__` using a lambda/table trick.  
> Partial indexes are super useful for speeding up “active/active+search” queries.

## 6) Check constraints

```python
from sqlalchemy import CheckConstraint

class LedgerEvent(ULIDPK, Timestamped, Base):
    __tablename__ = "ledger_event"
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    type:   Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "domain in ('admin','entity','customer','resource','sponsor','governance')",
            name="ck_ledger_domain"
        ),
    )
```

## 7) Relationships with back_populates

```python
class Entity(ULIDPK, Timestamped, Base):
    __tablename__ = "entity"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    people: Mapped[list["Person"]] = relationship(back_populates="entity", lazy="selectin")

class Person(ULIDPK, Timestamped, Base):
    __tablename__ = "person"
    entity_id: Mapped[str] = mapped_column(ForeignKey("entity.id"), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)

    entity: Mapped["Entity"] = relationship(back_populates="people")
```

## 8) Server defaults vs Python defaults

- `default=ulid_str` → evaluated in Python before INSERT

- `server_default=func.now()` → evaluated by DB engine

- You can use both: Python default for unit tests, server default in prod.

## 9) Hybrid columns (optional)

Useful when you want a computed attribute that can be used in queries:

```python
from sqlalchemy.ext.hybrid import hybrid_property

class Person(ULIDPK, Timestamped, Base):
    first_name: Mapped[str]
    last_name: Mapped[str]

    @hybrid_property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @full_name.expression
    def full_name(cls):
        from sqlalchemy import literal, concat
        return concat(cls.first_name, literal(" "), cls.last_name)
```

## 10) Putting it together (query + index usage)

```python
from sqlalchemy import select
from app.extensions import db
from app.lib.pagination import paginate_sa

def list_active_accounts(page: int = 1, per_page: int = 50):
    stmt = (
        select(Account)
        .where(Account.is_active == True)  # noqa: E712
        .order_by(Account.created_at.desc())
    )
    return paginate_sa(db.session, stmt, page=page, per_page=per_page)
```

---

## TL;DR

- **JSON helpers**: give you safe, canonical, hashable JSON and schema validation.

- **Indexes/constraints**: use `__table_args__` with `UniqueConstraint`, `CheckConstraint`, `Index` (functional/partial).

- **SQLite specifics**: functional & partial indexes via `text()` and `sqlite_where`.

- **Mixins**: `ULIDPK`, `Timestamped` keep models consistent.

- **Relationships**: `relationship(..., back_populates=...)` with association tables for many-to-many.

If you want, point me at one specific model (e.g., Governance `policy`, or Ledger `event`) and I’ll draft the exact `models.py` with the right indexes and constraints based on your current schema.

---

## Ledger Model

Let’s lock in a sturdy, JSON-centric Ledger model and a tiny service layer you can drop in. It’s SQLAlchemy 2.0 style, SQLite-friendly, and uses canonical JSON + SHA-256 for a verifiable hash chain.

---

# Ledger model (copy/paste ready)

```python
# app/slices/ledger/models.py
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Any, Dict, Optional

from sqlalchemy import (
    JSON, String, Text, DateTime, func, Index, CheckConstraint, ForeignKey, text
)
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase

# If you already have these mixins in app.lib.models, import them instead.
# from app.lib.models import Base, ULIDPK
class Base(DeclarativeBase): pass

def ulid_str() -> str:
    # or: from app.lib.ids import ulid_str
    from ulid import ULID
    return str(ULID())

# Canonical JSON tools; import your real helpers if you have them
def json_dumps_canonical(obj: Any) -> str:
    import json
    from datetime import datetime
    def default(o):
        if isinstance(o, datetime):
            # Always Zulu
            return o.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
        return str(o)
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False, default=default)

class ULIDPK:
    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=ulid_str)


class LedgerEvent(ULIDPK, Base):
    """
    Append-only, hash-chained, JSON-centric event.

    Hash covers the canonical JSON of the event payload + linkage fields,
    producing a tamper-evident chain (prev_event_id, prev_hash -> event_hash).
    """
    __tablename__ = "ledger_event"

    # --- Core identity / linkage ---
    prev_event_id: Mapped[Optional[str | None]] = mapped_column(
        String(26),
        ForeignKey(
            "ledger_event.id",
            name="fk_ledger_prev_event",
            ondelete="SET NULL",
        )
        nullable=True,
    )
    prev_hash:     Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # hex sha256
    event_hash:    Mapped[str]           = mapped_column(String(64), nullable=False, index=True)

    # --- Event classification ---
    # keep strings but constrain domain; “type” and “operation” are free-form enums you control
    domain:   Mapped[str] = mapped_column(String(32), nullable=False)   # e.g., admin|entity|customer|resource|sponsor|governance|...
    event_type: Mapped[str] = mapped_column(String(48), nullable=False) # e.g., policy.changed, roles.adjusted, etc.
    operation: Mapped[str] = mapped_column(String(48), nullable=False)  # e.g., create|update|delete|link|unlink

    # --- Time ---
    happened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # --- Chain Key / Correlation / request scope ---
    chain_key:      Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    request_id:     Mapped[Optional[str]] = mapped_column(String(26), nullable=True, index=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True, index=True)

    # --- Actors/Targets (entity ULIDs) ---
    actor_id:  Mapped[Optional[str]] = mapped_column(String(26), nullable=True, index=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True, index=True)

    # --- JSON payloads (as dicts for convenient ORM usage) ---
    # changed_fields: fields that changed (before/after, patch, etc.)
    changed_fields: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # refs: light-weight references (e.g., related IDs, external handles)
    refs:           Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # --- Canonical bytes (stored) for audit & hashing repeatability ---
    changed_fields_canon: Mapped[str] = mapped_column(Text, nullable=False)
    refs_canon:           Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        # Keep domain bounded (extend as you add slices)
        CheckConstraint(
            "domain IN ('admin','entity','customer','resource','sponsor','governance','calendar','logistics','transactions','ledger')",
            name="ck_ledger_domain"
        ),
        # Fast most-common filters
        Index("ix_ledger_domain_time", "domain", "happened_at"),
        Index("ix_ledger_actor_time", "actor_id", "happened_at"),
        Index("ix_ledger_target_time", "target_id", "happened_at"),
        Index("ix_ledger_corr_time", "correlation_id", "happened_at"),
        # Optional: prevent accidental dup hashes
        Index("uq_ledger_event_hash", "event_hash", unique=True),
        # Optional: composite indexes
        Index("ix_ledger_chain_key_happened", "chain_key", "happened_at"),
        Index("ix_ledger_corr_happened", "correlation_id", "happened_at"),
        Index("ix_ledger_domain_happened", "domain", "happened_at"),
    )

    # ---------- Hashing ----------
    @staticmethod
    def _hash_of(canonical: str) -> str:
        return sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical_body(
        *,
        domain: str,
        event_type: str,
        operation: str,
        happened_at: datetime,
        request_id: Optional[str],
        chain_key: str | None,
        correlation_id: Optional[str],
        actor_id: Optional[str],
        target_id: Optional[str],
        changed_fields_canon: str,
        refs_canon: str,
        prev_event_id: Optional[str],
        prev_hash: Optional[str],
    ) -> str:
        """
        Canonical JSON string of the event body (excluding event_hash).
        Order/keys are stable due to json_dumps_canonical.
        """
        body = {
            "domain": domain,
            "event_type": event_type,
            "operation": operation,
            "happened_at": happened_at,  # serializer converts to Zulu
            "request_id": request_id,
            "chain_key": chain_key,
            "correlation_id": correlation_id,
            "actor_id": actor_id,
            "target_id": target_id,
            "changed_fields_canon": changed_fields_canon,  # already canonical
            "refs_canon": refs_canon,                      # already canonical
            "prev_event_id": prev_event_id,
            "prev_hash": prev_hash,
        }
        return json_dumps_canonical(body)

    def compute_event_hash(self) -> str:
        """
        Compute the event_hash for current field values.
        """
        canon = self._canonical_body(
            domain=self.domain,
            event_type=self.event_type,
            operation=self.operation,
            happened_at=self.happened_at,
            request_id=self.request_id,
            chain_key=self.chain_key,
            correlation_id=self.correlation_id,
            actor_id=self.actor_id,
            target_id=self.target_id,
            changed_fields_canon=self.changed_fields_canon,
            refs_canon=self.refs_canon,
            prev_event_id=self.prev_event_id,
            prev_hash=self.prev_hash,
        )
        return self._hash_of(canon)

    # ---------- Factory ----------
    @classmethod
    def make(
        cls,
        *,
        domain: str,
        event_type: str,
        operation: str,
        happened_at: Optional[datetime] = None,
        request_id: Optional[str] = None,
        chain_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        target_id: Optional[str] = None,
        changed_fields: Optional[Dict[str, Any]] = None,
        refs: Optional[Dict[str, Any]] = None,
        prev_event_id: Optional[str] = None,
        prev_hash: Optional[str] = None,
    ) -> "LedgerEvent":
        changed_fields = changed_fields or {}
        refs = refs or {}
        changed_fields_canon = json_dumps_canonical(changed_fields)
        refs_canon = json_dumps_canonical(refs)

        self = cls(
            domain=domain,
            event_type=event_type,
            operation=operation,
            happened_at=happened_at or func.now(),  # SQL default handles it if None
            request_id=request_id,
            chain_key=chain_key,
            correlation_id=correlation_id,
            actor_id=actor_id,
            target_id=target_id,
            changed_fields=changed_fields,
            refs=refs,
            changed_fields_canon=changed_fields_canon,
            refs_canon=refs_canon,
            prev_event_id=prev_event_id,
            prev_hash=prev_hash,
            event_hash="",
        )
        # If happened_at is SQL default, event_hash will be recomputed after flush.
        # In practice we usually set explicit UTC now at the service layer.
        return self
```

---

# Minimal ledger service (append & latest)

```python
# app/slices/ledger/services.py
from __future__ import annotations
from typing import Optional, Dict, Any
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.slices.ledger.models import LedgerEvent
# Prefer your chrono helper for explicit timestamps
from app.lib.chrono import utc_now  # if you have it exposed

def latest_event(session: Session) -> Optional[LedgerEvent]:
    stmt = select(LedgerEvent).order_by(LedgerEvent.happened_at.desc()).limit(1)
    return session.execute(stmt).scalars().first()

def append_event(
    session: Session,
    *,
    domain: str,
    event_type: str,
    operation: str,
    request_id: Optional[str] = None,
    chain_key: str | None,
    correlation_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    target_id: Optional[str] = None,
    changed_fields: Optional[Dict[str, Any]] = None,
    refs: Optional[Dict[str, Any]] = None,
    happened_at: Optional[datetime] = None,
) -> LedgerEvent:
    """
    Append a new event to the global chain (simple single-chain example).
    If you prefer per-domain chains, fetch prev_* by (domain) instead of global latest.
    """
    prev = latest_event(session)
    ev = LedgerEvent.make(
        domain=domain,
        event_type=event_type,
        operation=operation,
        happened_at=happened_at or utc_now(),
        request_id=request_id,
        chain_key=chain_key,
        correlation_id=correlation_id,
        actor_id=actor_id,
        target_id=target_id,
        changed_fields=changed_fields,
        refs=refs,
        prev_event_id=prev.id if prev else None,
        prev_hash=prev.event_hash if prev else None,
    )
    # Compute hash with all fields set
    ev.event_hash = ev.compute_event_hash()
    session.add(ev)
    # Commit at the call site (so callers can batch multiple domain writes + one ledger append)
    return ev
```

---

## Chain Key / Correlation ID / Request ID Taxonomy

### What each field means

- **`chain_key`** (string like `project:<ulid>` or `grant:<ulid>`)
  
  - Purpose: groups events into a **narrative sub-chain** (timeline you can page through and/or hash-verify independently).
  
  - Stability: relatively **stable** across many events (the whole life of a project or grant).
  
  - Queries: “show me the project/grant history”; “compute burn-rate for grant X”; “list all events for chain_key = …”.

- **`correlation_id`** (ULID/UUID)
  
  - Purpose: ties together **all events spawned by one business action/workflow** (may span multiple requests/services).
  
  - Stability: **short-lived**; one id per workflow (e.g., “issue 3 items to customer 01H…” could emit 5–10 events sharing the same `correlation_id`).
  
  - Queries: “what did this operation do end-to-end?”; “roll back or replay just this one business action.”

- (Optional) **`request_id`** (ULID/UUID)
  
  - Purpose: trace events to a **single HTTP/request** execution for observability.
  
  - Stability: **one per request** (often injected by middleware).

### Why this setup works well

- `chain_key` gives you durable **sub-ledgers** (projects, grants, cases).

- `correlation_id` gives you **causality** and **idempotency** handles for a single action that may emit multiple events (retries write the same `correlation_id` so you can de-dupe).

- `request_id` helps ops/debug, not business logic; keep it too.

None obviate the others—they’re **orthogonal**:

| Field            | Scope                   | Lifetime                      | Primary use                   |
| ---------------- | ----------------------- | ----------------------------- | ----------------------------- |
| `chain_key`      | Project/Grant/Case      | Weeks–years                   | Sub-chain timelines & reports |
| `correlation_id` | One business action     | Seconds–minutes (maybe hours) | Tie multi-event workflows     |
| `request_id`     | One HTTP/RPC invocation | Milliseconds–seconds          | Tracing/observability         |

### Setting rules (practical)

- **Always set** `chain_key` when the event belongs to a known project/grant/case.  
  If none applies, use a domain key like `domain:governance` or `entity:<ulid>`—the point is to make queries cheap.

- **Always set** `correlation_id` for any multi-step action (propagate it across services). Generate once at the boundary; reuse within the workflow.

- **Always set** `request_id` in web handlers via middleware and pass it down.

### Query examples you’ll want

- Project timeline:
  
  ```sql
  SELECT * FROM ledger_event
   WHERE chain_key = 'project:01H...'
   ORDER BY happened_at;
  ```

- One operation’s footprint:
  
  ```sql
  SELECT * FROM ledger_event
   WHERE correlation_id = '01K...'
   ORDER BY happened_at;
  ```

- Troubleshoot a request:
  
  ```sql
  SELECT * FROM ledger_event
   WHERE request_id = '01K...'
   ORDER BY happened_at;
  ```

# Bottom line

Make `chain_key` **standard** to unlock fast per-project/grant reporting and optional sub-chain verification. Keep `correlation_id` and `request_id`—they’re **complementary**: correlation ties a single business action together; chain_key ties a long-lived story together; request_id ties runtime traces together.
