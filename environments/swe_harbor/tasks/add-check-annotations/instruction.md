# Add Check Annotations

The Healthchecks codebase is at `/app/`.

Add a way for users to attach short timestamped notes (annotations) to checks via the REST API — things like "deployed v2.0" or "server maintenance window".

## Requirements

- New `Annotation` model in `/app/hc/api/models.py` with fields: `code` (uuid), `owner` (FK to Check), `created`, `summary` (max 200 chars), `detail` (optional text), `tag` (optional, max 50 chars). Include a `to_dict()` and order by newest first.
- Generate and run the migration.
- `POST /api/v3/checks/<uuid:code>/annotations/` — create an annotation (write key required). Validate inputs, cap at 100 annotations per check.
- `GET /api/v3/checks/<uuid:code>/annotations/` — list annotations (read key). Support filtering by `tag`, `start`, and `end` query params.
- Use a dispatcher pattern for the annotations endpoint (look at how existing endpoints handle GET/POST on the same path). Add the URL route.
- Add `annotations_count` to `Check.to_dict()`.
- In `Check.prune()`, also clean up annotations older than the oldest retained ping (similar to how flips are pruned).

Don't modify existing tests. Follow the existing patterns in the codebase for decorators, error responses, and datetime formatting.
