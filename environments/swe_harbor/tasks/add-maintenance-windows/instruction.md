# Add Project Maintenance Windows

The Healthchecks codebase is at `/app/`. It's a Django app for monitoring cron jobs.

## What to build

Add a maintenance windows feature to the REST API so project owners can schedule maintenance periods. During an active maintenance window, checks in that project should report a `"maintenance"` status instead of `"up"`, `"down"`, or `"grace"`, and the API should reflect this state. This lets downstream consumers know that any downtime is expected and planned.

## 1. `MaintenanceWindow` model (`/app/hc/api/models.py`)

New model with these fields:

| Field | Type | Details |
|-------|------|---------|
| `code` | `UUIDField` | `default=uuid.uuid4, editable=False, unique=True` |
| `project` | `ForeignKey` to `Project` | `on_delete=models.CASCADE, related_name="maintenance_windows"` |
| `title` | `CharField` | `max_length=100` |
| `start_time` | `DateTimeField` | |
| `end_time` | `DateTimeField` | |
| `created` | `DateTimeField` | `default=now` |

Add `to_dict()` returning: `uuid`, `title`, `start_time` (ISO 8601, no microseconds), `end_time` (ISO 8601, no microseconds), `created` (ISO 8601, no microseconds).

Add `is_active(at=None)` method that returns `True` if the window is active at the given time (defaults to `now()`). A window is active when `start_time <= at < end_time` (half-open interval: inclusive start, exclusive end).

`Meta` class: `ordering = ["-created"]`.

## 2. Migration (`/app/hc/api/migrations/`)

Generate with `python manage.py makemigrations api`.

## 3. `Check.get_status()` modification (`/app/hc/api/models.py`)

Modify the existing `get_status()` method so that:

- If the check's status is `"new"` or `"paused"`, return it as-is (these are user-controlled states that should not be overridden).
- **Before** the existing grace/down logic, check if the check's project has any active maintenance window (a `MaintenanceWindow` where `start_time <= now < end_time`). If so, return `"maintenance"`.
- The `"maintenance"` status should take priority over `"up"`, `"down"`, `"grace"`, and `"started"` — the idea is that during planned maintenance, all active checks are expected to be disrupted.
- The rest of the existing status logic (`last_start`, grace period, etc.) remains unchanged for when no maintenance window is active.

## 4. `Check.to_dict()` modification (`/app/hc/api/models.py`)

Add `"in_maintenance"` (boolean) to the returned dict. This should be `True` if the check's project has any currently-active maintenance window, `False` otherwise. Note: this is independent of check status — even a paused or new check can have `in_maintenance=True`.

## 5. API endpoints (`/app/hc/api/views.py`)

### `POST /api/v3/maintenance/`

Create a maintenance window.

- Use `@authorize` (write key required)
- JSON body: `title` (required, string, max 100 chars), `start_time` (required, ISO 8601), `end_time` (required, ISO 8601)
- Validation:
  - `title` must be a non-empty string after stripping whitespace
  - `start_time` must be a valid ISO 8601 datetime
  - `end_time` must be a valid ISO 8601 datetime
  - `start_time` must be strictly before `end_time` (`400` with `{"error": "start_time must be before end_time"}`)
  - Duration cannot exceed 7 days (`400` with `{"error": "maintenance window cannot exceed 7 days"}`)
  - No overlapping windows for the same project. Two windows overlap when `start_time_A < end_time_B AND start_time_B < end_time_A`. Return `400` with `{"error": "overlapping maintenance window"}`.
  - Max 50 maintenance windows per project. Return `403` with `{"error": "too many maintenance windows"}` if at limit.
- Return the window JSON with status `201`
- `400` for validation errors (with `{"error": "..."}`)
- `401` for missing/wrong API key

### `GET /api/v3/maintenance/`

List maintenance windows for the project.

- Use `@authorize_read`
- Returns `{"windows": [...]}`
- Optional query param: `active=true` — only return currently-active windows
- `401` for missing/wrong API key

### `DELETE /api/v3/maintenance/<uuid:code>/`

Delete a maintenance window.

- Use `@authorize` (write key required) — apply decorators in this order: `@cors("DELETE")`, `@csrf_exempt`, `@authorize`
- `204` on success (empty response body)
- `403` if window belongs to a different project
- `404` if window doesn't exist
- `401` for missing/wrong API key

Wire up a dispatcher called `maintenance` that sends GET to the list handler and POST to the create handler. Decorate with `@csrf_exempt` and `@cors("GET", "POST")`.

## 6. URL routes (`/app/hc/api/urls.py`)

Add to the `api_urls` list (works across v1/v2/v3 automatically):

    path("maintenance/", views.maintenance, name="hc-api-maintenance"),
    path("maintenance/<uuid:code>/", views.delete_maintenance_window, name="hc-api-maintenance-delete"),

## Constraints

- Don't modify existing tests
- Use `isostring()` for datetime formatting (already in the codebase)
- Follow existing patterns for decorators, error responses, etc.
- The maintenance status check in `get_status()` must use a DB query against `MaintenanceWindow`, not a cached value
- `in_maintenance` in `to_dict()` should be evaluated independently (even paused/new checks can be in maintenance)
