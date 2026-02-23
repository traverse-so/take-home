# SWE Harbor Submission Notes

This submission includes three original SWE Harbor tasks designed to evaluate multi-step software engineering ability in a shared Django codebase (Healthchecks v3.6).

## Included Tasks

1. `add-maintenance-windows`
2. `add-bulk-operations`
3. `fix-tag-management-api`

## Why These Tasks Are Agent-Strong

### 1) add-maintenance-windows
- **Task type:** feature addition (model + API + routes + status integration)
- **Core reasoning challenge:** introduce a new cross-cutting concept (maintenance windows) that affects data model, API behavior, and check status logic.
- **Why it is hard for agents:** partial implementations can pass shallow API checks but fail status precedence and edge-boundary behavior.

### 2) add-bulk-operations
- **Task type:** feature extension with transactional correctness
- **Core reasoning challenge:** enforce all-or-nothing behavior across heterogeneous operations (`pause`, `resume`, `delete`, `add_tags`, `remove_tags`).
- **Why it is hard for agents:** must replicate subtle side effects from existing single-check endpoints while preserving atomicity and permissions.

### 3) fix-tag-management-api
- **Task type:** debug/fix + extension
- **Core reasoning challenge:** harden tag normalization/validation and project-scoped behavior while introducing multiple endpoints with quoted URL routing.
- **Why it is hard for agents:** combines data cleanup semantics, constraints, and access control across multiple files.

## Multi-File Dependency Map

### add-maintenance-windows
- `hc/api/models.py`
  - new `MaintenanceWindow` model
  - `Check.get_status()` maintenance override logic
  - `Check.to_dict()` `in_maintenance` field
- `hc/api/views.py`
  - create/list/delete maintenance endpoints
- `hc/api/urls.py`
  - route wiring for maintenance endpoints
- migration under `hc/api/migrations/`

### add-bulk-operations
- `hc/api/models.py`
  - `Check.bulk_tags_add()`, `Check.bulk_tags_remove()` helpers
- `hc/api/views.py`
  - `bulk_checks` endpoint with validation + atomic apply
- `hc/api/urls.py`
  - `/checks/bulk/` route placement before `/checks/<uuid:code>`

### fix-tag-management-api
- `hc/api/models.py`
  - tag helpers (`clean_tags`, `add_tag`, `remove_tag`)
- `hc/api/views.py`
  - check tag list/add/remove and project tag summary endpoints
- `hc/api/urls.py`
  - routes using `<quoted:tag>` converter

## Key Logic Traps Covered by Tests

### add-maintenance-windows
- half-open interval boundary semantics (`start <= t < end`)
- overlap detection correctness
- status precedence interactions with `new` and `paused`
- in-maintenance serialization independent of check status

### add-bulk-operations
- strict validation-before-apply
- atomic rollback on mixed ownership or missing checks
- side-effect parity with existing pause/resume behavior (flip creation / field reset)
- route ordering trap (`checks/bulk` vs `checks/<uuid>`)

### fix-tag-management-api
- deduplication while preserving order
- strict tag regex and constraints
- project-level isolation (no cross-project tag leaks)
- URL-encoded tag handling through `<quoted:tag>`

## Test Inventory (within 20-40 target)

- `add-maintenance-windows`: **40** tests
- `add-bulk-operations`: **32** tests
- `fix-tag-management-api`: **35** tests

## Reproducible Verification Commands

Run from:

```bash
cd /Users/isabellelu/Desktop/traverse-take-home/environments/swe_harbor
```

Build image once:

```bash
docker build -t swe-harbor environment/
```

Run matrix:

```bash
for t in add-maintenance-windows add-bulk-operations fix-tag-management-api; do
  echo "=== $t WITH solution ==="
  docker run --rm \
    -v $(pwd)/tasks/$t/solution:/solution \
    -v $(pwd)/tasks/$t/tests:/tests \
    swe-harbor \
    bash -lc "mkdir -p /logs/verifier && cd /app && bash /solution/solve.sh && bash /tests/test.sh && cat /logs/verifier/reward.txt"

  echo "=== $t WITHOUT solution ==="
  docker run --rm \
    -v $(pwd)/tasks/$t/tests:/tests \
    swe-harbor \
    bash -lc "mkdir -p /logs/verifier && bash /tests/test.sh && cat /logs/verifier/reward.txt"
done
```

## Verification Matrix (expected and achieved)

- `add-maintenance-windows`: with solution **1**, without solution **0**
- `add-bulk-operations`: with solution **1**, without solution **0**
- `fix-tag-management-api`: with solution **1**, without solution **0**

This satisfies Harbor task validity requirements and demonstrates that tests are non-trivial (they fail against baseline code and pass with reference solutions).
