# VCDB v2 - Usage Examples

This document provides examples of how to use the VCDB v2 architecture following the VCDB Ethos principles.

## Architecture Overview

```
app/
├── lib/                    # Shared primitives (database, middleware, types)
├── extensions/            # Inter-slice bridge
│   └── contract/          # Contracts for cross-slice communication
└── slices/                # Vertical slices (self-contained features)
    ├── users/
    └── services/
```

## Example 1: Creating a User (Route → Service)

### Route Layer (Owns Transaction)
```python
from app.slices.users.routes.user_routes import create_user_route

# Headers should contain x-request-id
headers = {"x-request-id": "client-123"}

# Route manages transaction
result = create_user_route(
    headers=headers,
    name="John Doe",
    email="john@example.com",
    veteran_id="VET-001"
)

print(result)
# {
#   "status": "success",
#   "request_id": "client-123",
#   "data": {"id": 1, "name": "John Doe", ...}
# }
```

### What Happens Internally:

1. **Route gets request_id** (from headers or generates it)
   ```python
   request_id = get_or_create_request_id(headers)
   ```

2. **Route creates database session**
   ```python
   with get_db_session() as db:
   ```

3. **Route calls service** (passes request_id)
   ```python
   user = user_service.create(db, request_id, name, email, veteran_id)
   ```

4. **Service performs business logic and flushes**
   ```python
   db.add(user)
   db.flush()  # Only flush, never commit
   ```

5. **Route commits transaction**
   ```python
   db.commit()  # Route owns commit/rollback
   ```

## Example 2: Inter-Slice Communication

When the `services` slice needs to access `users` data:

### ❌ WRONG - Direct Import
```python
# DO NOT DO THIS
from app.slices.users.services.user_service import user_service

def create_service_request(db, request_id, user_id):
    # Direct access to another slice - VIOLATES architecture
    user = user_service.get_by_id(db, request_id, user_id)
```

### ✅ CORRECT - Use Extension Contract
```python
from app.extensions.contract.user_contract import user_contract

def create_service_request(db, request_id, user_id, service_type, description):
    # Access through contract - follows architecture
    is_veteran = user_contract.verify_veteran_status(db, request_id, user_id)
    
    if not is_veteran:
        raise ValueError("User is not a verified veteran")
    
    # Continue with business logic...
```

## Example 3: Request ID Flow

### Client Provides request_id
```python
headers = {"x-request-id": "my-correlation-id"}
result = create_user_route(headers, "Jane", "jane@example.com")
# Uses: my-correlation-id
```

### No request_id Provided (Generated at Route Entry)
```python
headers = {}
result = create_user_route(headers, "Jane", "jane@example.com")
# Generated: f47ac10b-58cc-4372-a567-0e02b2c3d479 (example UUID)
```

### request_id Appears in All Logs
```
INFO - Creating user: jane@example.com [request_id=my-correlation-id]
INFO - User created: User(id=1, name=Jane) [request_id=my-correlation-id]
```

## Key Principles Demonstrated

### 1. Routes Own Transactions
- Routes call `db.commit()` and `db.rollback()`
- Services never commit or rollback

### 2. Services Only Flush
- Services call `db.flush()` to sync with database
- No transaction control in services

### 3. request_id is Mandatory
- All operations require request_id
- request_id used for correlation, not session management

### 4. request_id Never Generated in Services
- Only generated at route entry point
- Services receive request_id as parameter

### 5. Vertical Slices are Isolated
- Each slice has its own models, services, routes
- No direct cross-slice imports

### 6. Extensions Bridge Slices
- All inter-slice communication through `extensions/contract`
- Contracts provide well-defined interfaces

### 7. Shared Code in app/lib
- Database configuration
- Middleware
- Common types
- No business logic

## Running Tests

```bash
pytest tests/test_architecture_compliance.py -v
```

Tests verify:
- ✅ Services only flush
- ✅ request_id validation works
- ✅ Routes commit transactions
- ✅ Extension contracts exist
- ✅ Database session behavior

## Directory Structure Explanation

```
app/slices/users/          # Users slice (vertical)
├── models/                # User data models
│   └── user.py
├── services/              # User business logic
│   └── user_service.py   # Only flushes, receives request_id
└── routes/                # User endpoints
    └── user_routes.py    # Owns transactions, manages request_id

app/slices/services/       # Service requests slice (vertical)
├── models/
│   └── service_request.py
├── services/
│   └── service_request_service.py  # Uses user_contract, not direct import
└── routes/

app/extensions/contract/   # Cross-slice communication
└── user_contract.py      # How other slices access users

app/lib/                   # Shared primitives
├── database/
│   └── session.py        # DB session management
├── middleware/
│   └── correlation.py    # request_id handling
└── types/
    └── context.py        # Shared types
```

## Best Practices

1. **Always pass request_id** to service methods
2. **Never commit/rollback in services** - only flush
3. **Use contracts for cross-slice calls** - never direct imports
4. **Routes manage the full request lifecycle**
5. **Log with request_id** for observability
6. **Keep slices independent** - own your data
7. **Share primitives only** - no business logic in lib/
