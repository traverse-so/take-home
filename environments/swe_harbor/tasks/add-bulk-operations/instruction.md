# Add Bulk Check Operations API

The Healthchecks codebase is at `/app/`. It's a Django app for monitoring cron jobs.

## What to build

Add an API endpoint for performing bulk operations on multiple checks at once: pause, resume, delete, and tag management. All operations must be **atomic** — if any check fails validation (doesn't exist, wrong project, etc.), the entire operation must be rolled back with no partial changes.

## 1. `Check.bulk_tags_add()` and `Check.bulk_tags_remove()` helpers (`/app/hc/api/models.py`)

Add two helper methods to the `Check` model:

### `bulk_tags_add(self, new_tags: list[str]) -> None`

Adds tags to the check's existing tags without creating duplicates. The check's `tags` field is a space-separated `CharField(max_length=500)`. Steps:
1. Parse existing tags with `self.tags_list()`
2. Append only tags not already present
3. Rebuild the space-separated string
4. Save the check

### `bulk_tags_remove(self, remove_tags: list[str]) -> None`

Removes specified tags from the check. Steps:
1. Parse existing tags with `self.tags_list()`
2. Filter out the tags to remove
3. Rebuild the space-separated string
4. Save the check

## 2. API endpoint (`/app/hc/api/views.py`)

### `POST /api/v3/checks/bulk/`

Perform a bulk operation on multiple checks.

- Decorate with `@cors("POST")`, `@csrf_exempt`, `@authorize` (in that order, outermost first)
- JSON body:
  - `action` (required): one of `"pause"`, `"resume"`, `"delete"`, `"add_tags"`, `"remove_tags"`
  - `checks` (required): list of check UUID strings
  - `tags` (required for `add_tags` and `remove_tags`): space-separated tag string (e.g., `"deploy production"`)

#### Validation (check these before performing any operation):
- `action` must be one of the five valid actions. `400` with `{"error": "invalid action"}` if not.
- `checks` must be a list. `400` with `{"error": "checks must be a list"}` if not.
- `checks` must not be empty. `400` with `{"error": "checks must not be empty"}` if empty.
- `checks` must have at most 50 entries. `400` with `{"error": "too many checks (max 50)"}` if exceeded.
- Each entry in `checks` must be a valid UUID string. `400` with `{"error": "invalid check uuid"}` if any are not.
- Every check UUID must exist. `404` with `{"error": "check not found"}` if any don't exist.
- **Every check must belong to the requesting project.** `403` with `{"error": "check does not belong to this project"}` if any don't. This is the key atomicity requirement — if a user includes 9 of their own checks and 1 from another project, the entire operation fails.
- For `add_tags` and `remove_tags`: `tags` must be present and non-empty. `400` with `{"error": "tags is required"}` if missing.

#### Operation behavior (inside `transaction.atomic()`):

**`pause`**: For each check that is not already paused:
- Call `check.create_flip("paused", mark_as_processed=True)` (same as the existing `pause` endpoint)
- Set `status = "paused"`, `last_start = None`, `alert_after = None`
- Save the check
- After all checks: call `request.project.update_next_nag_dates()`

**`resume`**: For each check that is currently paused:
- Call `check.create_flip("new", mark_as_processed=True)`
- Set `status = "new"`, `last_start = None`, `last_ping = None`, `alert_after = None`
- Save the check

**`delete`**: For each check:
- Call `check.lock_and_delete()` (existing pattern that acquires a DB lock before deleting)

**`add_tags`**: For each check:
- Call `check.bulk_tags_add(tag_list)` where `tag_list` is the tags string split into a list

**`remove_tags`**: For each check:
- Call `check.bulk_tags_remove(tag_list)`

#### Response:

On success, return `200` with:
```json
{
    "applied": <number of checks affected>,
    "action": "<action name>"
}
```

For `pause`: `applied` counts checks that were actually paused (excludes already-paused checks).
For `resume`: `applied` counts checks that were actually resumed (excludes non-paused checks).
For `delete`: `applied` counts all deleted checks.
For `add_tags`/`remove_tags`: `applied` counts all checks in the request.

## 3. URL routes (`/app/hc/api/urls.py`)

Add to the `api_urls` list:

    path("checks/bulk/", views.bulk_checks, name="hc-api-bulk"),

**Important**: This route must be placed **before** the existing `path("checks/<uuid:code>", ...)` route so Django doesn't try to interpret `"bulk"` as a UUID.

## Constraints

- Don't modify existing tests
- The entire operation must be inside `transaction.atomic()` — no partial updates
- All validation must happen before any modifications begin
- Follow existing patterns for decorators, error responses, etc.
- The `pause` and `resume` logic must match the existing single-check endpoints exactly (flip creation, field resets, nag date updates)
- Do not skip checks silently — validate ALL checks belong to the project before proceeding
