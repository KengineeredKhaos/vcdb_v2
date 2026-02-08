# VCDB v2 - Veteran Service Organization Database System

A database system for a Non-profit Veteran Service Organization, built following clean architecture principles.

## Architecture

VCDB v2 follows the **VCDB Ethos** - a set of architectural principles designed for maintainability, observability, and modularity.

### Key Principles

1. **Nothing Happens in the Dark** - All operations are traceable via correlation IDs
2. **Routes Own Transactions** - Transaction scope is managed at the route layer
3. **Services Flush Only** - Business logic never commits or rolls back
4. **Correlation is Mandatory** - Every operation includes a `request_id`
5. **Vertical Slices** - Features are isolated, no cross-slice imports
6. **Extensions Bridge** - Inter-slice communication through contracts only
7. **Shared Primitives** - Common code lives in `app/lib/`

See [VCDB Ethos (updated).md](VCDB%20Ethos%20%28updated%29.md) for detailed architectural guidelines.

## Project Structure

```
app/
├── lib/                    # Shared primitives
│   ├── database/          # Database configuration
│   ├── middleware/        # Common middleware (e.g., correlation)
│   └── types/             # Shared types
├── extensions/            # Inter-slice communication bridge
│   └── contract/          # Slice contracts
└── slices/                # Vertical slices (features)
    ├── users/             # User management
    └── services/          # Service requests
```

## Quick Start

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run Tests

```bash
pytest tests/ -v
```

## Usage Examples

See [EXAMPLES.md](EXAMPLES.md) for detailed usage examples.

### Creating a User

```python
from app.slices.users.routes.user_routes import create_user_route

headers = {"x-request-id": "my-request-id"}
result = create_user_route(headers, "John Doe", "john@example.com", "VET-001")
```

### Inter-Slice Communication

```python
from app.extensions.contract.user_contract import user_contract

# Correct: Use contract to access user data from another slice
is_veteran = user_contract.verify_veteran_status(db, request_id, user_id)
```

## Documentation

- [VCDB Ethos (updated).md](VCDB%20Ethos%20%28updated%29.md) - Architecture principles and guidelines
- [EXAMPLES.md](EXAMPLES.md) - Code examples and usage patterns

## Architecture Compliance

The codebase includes tests to validate architectural compliance:

- ✅ Services only flush, never commit/rollback
- ✅ request_id is mandatory for all operations
- ✅ Services receive request_id, never generate it
- ✅ Inter-slice communication uses extension contracts
- ✅ Routes own transaction scope

Run compliance tests:

```bash
pytest tests/test_architecture_compliance.py -v
```
