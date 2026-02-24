# Add Check Transfer API

The Healthchecks codebase is at `/app/`.

Add the ability to transfer a check from one project to another via the REST API, with an audit log of past transfers.

## Requirements

- New `TransferLog` model in `/app/hc/api/models.py` to record each transfer. Track which check was transferred, the source and target projects, when it happened, and who did it (API key owner's email). Include a `to_dict()`. If a project gets deleted, keep the log around (don't cascade).
- Generate and run the migration.
- Add a `Check.transfer(target_project, transferred_by="")` method that atomically: validates the target project has capacity, logs the transfer, moves the check, reassigns channels to the target project's channels, resets the check's alert state, and cleans up old pings/flips. Use the same locking pattern as other critical Check methods in the codebase.
- `POST /api/v3/checks/<uuid:code>/transfer/` — transfer a check (write key required). Body takes a `project` UUID and a `target_api_key` to authorize against the target project. Validate everything sensibly (missing fields, invalid UUIDs, same-project transfers, capacity).
- `GET /api/v3/checks/<uuid:code>/transfers/` — list transfer history for a check (read key).
- Add URL routes for both endpoints.
- Add `transfers_count` to `Check.to_dict()`.

Don't modify existing tests. The transfer must be fully atomic. Follow existing codebase patterns for decorators, error handling, and authorization.
