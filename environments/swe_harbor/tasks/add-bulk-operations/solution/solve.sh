#!/bin/bash
set -e
cd /app

###############################################################################
# 1. Add bulk_tags_add and bulk_tags_remove helpers to Check model
###############################################################################

python3 << 'PATCH1'
with open("hc/api/models.py", "r") as f:
    content = f.read()

old = '''    def tags_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(" ") if t.strip()]'''

new = '''    def tags_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(" ") if t.strip()]

    def bulk_tags_add(self, new_tags: list[str]) -> None:
        """Add tags without creating duplicates."""
        existing = self.tags_list()
        for tag in new_tags:
            tag = tag.strip()
            if tag and tag not in existing:
                existing.append(tag)
        self.tags = " ".join(existing)
        self.save()

    def bulk_tags_remove(self, remove_tags: list[str]) -> None:
        """Remove specified tags."""
        remove_set = set(t.strip() for t in remove_tags)
        existing = self.tags_list()
        self.tags = " ".join(t for t in existing if t not in remove_set)
        self.save()'''

content = content.replace(old, new, 1)

with open("hc/api/models.py", "w") as f:
    f.write(content)
PATCH1

###############################################################################
# 2. Add bulk operation API view
###############################################################################

cat >> /app/hc/api/views.py << 'VIEWEOF'


@cors("POST")
@csrf_exempt
@authorize
def bulk_checks(request: ApiRequest) -> HttpResponse:
    action = request.json.get("action", "")
    if action not in ("pause", "resume", "delete", "add_tags", "remove_tags"):
        return JsonResponse({"error": "invalid action"}, status=400)

    checks_list = request.json.get("checks", None)
    if not isinstance(checks_list, list):
        return JsonResponse({"error": "checks must be a list"}, status=400)

    if len(checks_list) == 0:
        return JsonResponse({"error": "checks must not be empty"}, status=400)

    if len(checks_list) > 50:
        return JsonResponse({"error": "too many checks (max 50)"}, status=400)

    # Validate all UUIDs and resolve checks
    resolved = []
    for raw_uuid in checks_list:
        try:
            check_uuid = UUID(str(raw_uuid))
        except (ValueError, AttributeError):
            return JsonResponse({"error": "invalid check uuid"}, status=400)

        try:
            check = Check.objects.get(code=check_uuid)
        except Check.DoesNotExist:
            return JsonResponse({"error": "check not found"}, status=404)

        if check.project_id != request.project.id:
            return JsonResponse(
                {"error": "check does not belong to this project"}, status=403
            )

        resolved.append(check)

    # Validate tags for tag operations
    tags_str = ""
    tag_list = []
    if action in ("add_tags", "remove_tags"):
        tags_str = request.json.get("tags", "")
        if not isinstance(tags_str, str) or not tags_str.strip():
            return JsonResponse({"error": "tags is required"}, status=400)
        tag_list = [t.strip() for t in tags_str.split() if t.strip()]

    # Perform the operation atomically
    applied = 0

    with transaction.atomic():
        if action == "pause":
            for check in resolved:
                if check.status != "paused":
                    check.create_flip("paused", mark_as_processed=True)
                    check.status = "paused"
                    check.last_start = None
                    check.alert_after = None
                    check.save()
                    applied += 1
            request.project.update_next_nag_dates()

        elif action == "resume":
            for check in resolved:
                if check.status == "paused":
                    check.create_flip("new", mark_as_processed=True)
                    check.status = "new"
                    check.last_start = None
                    check.last_ping = None
                    check.alert_after = None
                    check.save()
                    applied += 1

        elif action == "delete":
            for check in resolved:
                check.lock_and_delete()
                applied += 1

        elif action == "add_tags":
            for check in resolved:
                check.bulk_tags_add(tag_list)
                applied += 1

        elif action == "remove_tags":
            for check in resolved:
                check.bulk_tags_remove(tag_list)
                applied += 1

    return JsonResponse({"applied": applied, "action": action})
VIEWEOF

###############################################################################
# 3. Add URL route (before the existing checks/<uuid:code> route)
###############################################################################

python3 << 'PATCH2'
with open("hc/api/urls.py", "r") as f:
    content = f.read()

old = '    path("checks/", views.checks),'

new = '''    path("checks/bulk/", views.bulk_checks, name="hc-api-bulk"),
    path("checks/", views.checks),'''

content = content.replace(old, new, 1)

with open("hc/api/urls.py", "w") as f:
    f.write(content)
PATCH2
