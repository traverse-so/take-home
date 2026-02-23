# Fix Tag Management API Regressions

The Healthchecks codebase is at `/app/`. It's a Django app for monitoring cron jobs.

## Context

A recent refactor attempted to add explicit tag-management endpoints, but the implementation was never merged cleanly and behavior is currently missing/incorrect. You need to implement and stabilize this API so tag operations are safe, deterministic, and project-scoped.

This is intentionally a **debug/fix** style task: you must preserve existing check behavior while adding correct tag-management primitives and endpoints.

## Files expected to change

- `/app/hc/api/models.py`
- `/app/hc/api/views.py`
- `/app/hc/api/urls.py`

## 1. Model helper methods (`/app/hc/api/models.py`)

Extend `Check` with helper methods right around the existing `tags_list()` / `matches_tag_set()` logic:

1. `clean_tags(self) -> list[str]`
- Return de-duplicated tags while preserving order.
- Ignore empty tokens.

2. `add_tag(self, tag: str) -> bool`
- Add tag only if not already present.
- Save the updated `tags` field.
- Return `True` if changed, `False` if tag already existed.

3. `remove_tag(self, tag: str) -> bool`
- Remove tag if present.
- Save the updated `tags` field.
- Return `True` if changed, `False` otherwise.

These helpers are used by the API views and must be reliable across malformed legacy tag strings (extra spaces, duplicates).

## 2. API endpoints (`/app/hc/api/views.py`)

Implement the following endpoints and supporting functions.

### A) `GET /api/v3/checks/<uuid:code>/tags/`

- Use `@authorize_read`.
- Return `{"tags": ["...", ...]}` using normalized tags (`clean_tags()` order).
- `403` if check belongs to another project.
- `404` if check not found.

### B) `POST /api/v3/checks/<uuid:code>/tags/<quoted:tag>/`

- Use `@authorize`.
- Add one tag to one check.
- Validation:
  - Tag regex: `^[A-Za-z0-9._~-]{1,50}$`
  - Invalid tag => `400` with `{"error": "invalid tag"}`
- Constraints:
  - Max 20 tags per check (`400` + `{"error": "too many tags"}`)
  - Final serialized `Check.tags` length must stay `<= 500` (`400` + `{"error": "tags field is too long"}`)
- Response:
  - If newly added: `201` with `{"added": true, "tags": [...]}`
  - If already present: `200` with `{"added": false, "tags": [...]}`
- `403` for wrong project, `404` for missing check.

### C) `DELETE /api/v3/checks/<uuid:code>/tags/<quoted:tag>/`

- Use `@authorize`.
- Remove one tag from one check.
- Same tag validation as above (`400` invalid tag).
- If tag exists and removed: return `204` (empty body).
- If tag does not exist on the check: `404` with `{"error": "tag not found"}`.
- `403` for wrong project, `404` for missing check.

### D) `GET /api/v3/tags/`

- Use `@authorize_read`.
- Return unique tag summary for the authenticated project only:
  - `{"tags": [{"name": "deploy", "count": 3}, ...]}`
- Count each tag at most once per check (use normalized tags).
- Sort results by tag name ascending.
- Optional query param: `prefix`
  - If supplied and non-empty, return only tags whose names start with that prefix.

### Dispatcher/cors wrappers

Add dispatcher functions with existing project style:

- `check_tags` for endpoint A, with `@csrf_exempt` + `@cors("GET")`
- `single_tag` for endpoints B/C, with `@csrf_exempt` + `@cors("POST", "DELETE")`
- `project_tags` for endpoint D, with `@csrf_exempt` + `@cors("GET")`

## 3. URL routes (`/app/hc/api/urls.py`)

Add to `api_urls`:

```python
path("checks/<uuid:code>/tags/", views.check_tags, name="hc-api-check-tags"),
path("checks/<uuid:code>/tags/<quoted:tag>/", views.single_tag, name="hc-api-single-tag"),
path("tags/", views.project_tags, name="hc-api-project-tags"),
```

Important:
- Use `<quoted:tag>` (QuoteConverter already exists in this file).
- This must support URL-encoded tag values.

## Acceptance Criteria

- Required routes exist and are reachable under `/api/v1/`, `/api/v2/`, `/api/v3/`:
  - `GET /checks/<uuid>/tags/`
  - `POST /checks/<uuid>/tags/<quoted:tag>/`
  - `DELETE /checks/<uuid>/tags/<quoted:tag>/`
  - `GET /tags/`
- Helper methods are present and behave as specified:
  - `clean_tags()` de-duplicates while preserving order
  - `add_tag()` and `remove_tag()` return boolean change indicators
- Validation and response semantics are exact:
  - invalid tag -> `400` with `{"error": "invalid tag"}`
  - missing tag on remove -> `404` with `{"error": "tag not found"}`
  - max-tags / max-length constraints enforced
- Project-level tag listing is strictly scoped to authenticated project and supports prefix filter.
- URL-encoded tags are supported through `<quoted:tag>`.
- Handled validation and permission errors must return JSON in the form `{"error": "<message>"}`.

## Constraints

- Don't modify existing tests.
- Follow existing patterns for decorators, permission checks, and JSON error responses.
- Keep all tag operations strictly project-scoped (no cross-project tag leakage).

## Non-goals

- Do not redesign tag storage away from the existing `Check.tags` string field.
- Do not change unrelated check filtering/search behavior.
- Do not add new auth schemes; use existing key-based auth/decorators.

## Why this is hard

- The task mixes normalization, validation, permissions, and URL routing (`<quoted:tag>`) across files.
- Deduplication must preserve order and still keep API/project aggregation correct.
- Cross-project leakage bugs are easy to introduce if queryset scoping is not exact.
