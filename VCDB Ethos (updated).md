# VCDB Ethos (updated)

## Core Principle: Nothing Happens in the Dark
All operations must be traceable and observable through correlation IDs.

## Architecture & Slice Boundaries

### Transaction Ownership
- **Routes own the transaction scope**
  - Routes are responsible for beginning, committing, and rolling back transactions
  - Routes coordinate the overall flow of a request
  - Services never manage transactions directly

### Service Layer
- **Services flush only**
  - Services perform business logic and prepare data changes
  - Services call `session.flush()` to synchronize with the database
  - Services never commit or rollback transactions
  - Transaction control remains with the route layer

### Correlation & Observability
- **Correlation is mandatory (`request_id`)**
  - Every request must have a `request_id` for tracing
  - `request_id` is a correlation ID, not a transaction/session handle
  - **Never generate `request_id` inside services**
  - Services receive `request_id` as a parameter from routes
  - `request_id` is used for logging, tracing, and debugging

### Vertical Slice Architecture
- **Vertical slices own their data**
  - Each slice has its own models, services, and routes
  - No cross-slice imports allowed
  - Slices are self-contained feature areas
  
### Inter-Slice Communication
- **Extensions is the only bridge**
  - All inter-slice calls go through `extensions/contract`
  - Extensions provide well-defined interfaces between slices
  - No direct dependencies between slices

### Shared Code
- **app/lib/ = shared primitives**
  - Common utilities, types, and primitives
  - Database configuration and base models
  - Middleware and decorators
  - No business logic in shared code

## Directory Structure
```
app/
├── lib/                    # Shared primitives
│   ├── database/          # DB configuration
│   ├── middleware/        # Common middleware
│   └── types/             # Shared types
├── extensions/            # Inter-slice bridge
│   └── contract/          # Slice contracts
└── slices/                # Vertical slices
    ├── slice_a/
    │   ├── models/
    │   ├── services/
    │   └── routes/
    └── slice_b/
        ├── models/
        ├── services/
        └── routes/
```

## Implementation Guidelines

### Route Layer Example
```python
@router.post("/users")
async def create_user(request_id: str, data: UserCreate, db: Session):
    """Route owns the transaction scope"""
    try:
        # Route receives request_id from middleware
        user = user_service.create(db, request_id, data)
        db.commit()  # Route commits
        return user
    except Exception as e:
        db.rollback()  # Route rolls back
        raise
```

### Service Layer Example
```python
def create(db: Session, request_id: str, data: UserCreate):
    """Service receives request_id, never generates it"""
    # Log with correlation ID
    logger.info(f"Creating user", extra={"request_id": request_id})
    
    # Business logic
    user = User(**data.dict())
    db.add(user)
    db.flush()  # Service only flushes
    
    return user
```

### Extension Contract Example
```python
# extensions/contract/user_contract.py
class UserContract:
    """Contract for accessing user data from other slices"""
    
    @staticmethod
    def get_user_by_id(db: Session, request_id: str, user_id: int):
        """Other slices call this, not direct imports"""
        from app.slices.users.services import user_service
        return user_service.get_by_id(db, request_id, user_id)
```

## Validation Rules
1. ✅ Routes must manage transactions (commit/rollback)
2. ✅ Services must only flush
3. ✅ All operations must include request_id parameter
4. ❌ Services must never generate request_id
5. ❌ No direct imports between slices
6. ✅ Inter-slice calls must go through extensions/contract
7. ✅ Shared code lives in app/lib/
