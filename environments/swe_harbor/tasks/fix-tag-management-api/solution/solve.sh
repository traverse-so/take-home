#!/bin/bash
set -e
cd /app

###############################################################################
# 1. Add Check tag helper methods
###############################################################################

python3 << 'PATCH1'
from pathlib import Path

path = Path("hc/api/models.py")
content = path.read_text()
old = '''    def tags_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(" ") if t.strip()]

    def matches_tag_set(self, tag_set: set[str]) -> bool:
        return tag_set.issubset(self.tags_list())'''
new = '''    def tags_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(" ") if t.strip()]

    def clean_tags(self) -> list[str]:
        seen = set()
        result = []
        for tag in self.tags_list():
            if tag not in seen:
                seen.add(tag)
                result.append(tag)
        return result

    def add_tag(self, tag: str) -> bool:
        tags = self.clean_tags()
        if tag in tags:
            return False

        tags.append(tag)
        self.tags = " ".join(tags)
        self.save(update_fields=["tags"])
        return True

    def remove_tag(self, tag: str) -> bool:
        tags = self.clean_tags()
        if tag not in tags:
            return False

        self.tags = " ".join(t for t in tags if t != tag)
        self.save(update_fields=["tags"])
        return True

    def matches_tag_set(self, tag_set: set[str]) -> bool:
        return tag_set.issubset(self.tags_list())'''
if old not in content:
    raise SystemExit("expected tags_list block not found")
path.write_text(content.replace(old, new, 1))
PATCH1

###############################################################################
# 2. Add tag management API views
###############################################################################

cat >> /app/hc/api/views.py << 'VIEWEOF'


def _validate_tag_value(value: str) -> str:
    import re

    tag = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._~-]{1,50}", tag):
        raise ValueError("invalid tag")
    return tag


@authorize_read
def get_check_tags(request: ApiRequest, code: UUID) -> HttpResponse:
    check = get_object_or_404(Check, code=code)
    if check.project_id != request.project.id:
        return HttpResponseForbidden()

    return JsonResponse({"tags": check.clean_tags()})


@authorize
def add_check_tag(request: ApiRequest, code: UUID, tag: str) -> HttpResponse:
    check = get_object_or_404(Check, code=code)
    if check.project_id != request.project.id:
        return HttpResponseForbidden()

    try:
        tag = _validate_tag_value(tag)
    except ValueError:
        return JsonResponse({"error": "invalid tag"}, status=400)

    tags = check.clean_tags()
    if tag not in tags:
        if len(tags) >= 20:
            return JsonResponse({"error": "too many tags"}, status=400)

        candidate = " ".join(tags + [tag])
        if len(candidate) > 500:
            return JsonResponse({"error": "tags field is too long"}, status=400)

    added = check.add_tag(tag)
    return JsonResponse(
        {
            "added": added,
            "tags": check.clean_tags(),
        },
        status=201 if added else 200,
    )


@authorize
def remove_check_tag(request: ApiRequest, code: UUID, tag: str) -> HttpResponse:
    check = get_object_or_404(Check, code=code)
    if check.project_id != request.project.id:
        return HttpResponseForbidden()

    try:
        tag = _validate_tag_value(tag)
    except ValueError:
        return JsonResponse({"error": "invalid tag"}, status=400)

    removed = check.remove_tag(tag)
    if not removed:
        return JsonResponse({"error": "tag not found"}, status=404)

    return HttpResponse(status=204)


@authorize_read
def get_project_tags(request: ApiRequest) -> HttpResponse:
    prefix = request.GET.get("prefix", "")
    counts: dict[str, int] = {}

    checks = Check.objects.filter(project=request.project).only("tags")
    for check in checks:
        for tag in check.clean_tags():
            counts[tag] = counts.get(tag, 0) + 1

    tags = []
    for name, count in sorted(counts.items()):
        if prefix and not name.startswith(prefix):
            continue
        tags.append({"name": name, "count": count})

    return JsonResponse({"tags": tags})


@csrf_exempt
@cors("GET")
def check_tags(request: HttpRequest, code: UUID) -> HttpResponse:
    return get_check_tags(request, code)


@csrf_exempt
@cors("POST", "DELETE")
def single_tag(request: HttpRequest, code: UUID, tag: str) -> HttpResponse:
    if request.method == "POST":
        return add_check_tag(request, code, tag)

    return remove_check_tag(request, code, tag)


@csrf_exempt
@cors("GET")
def project_tags(request: HttpRequest) -> HttpResponse:
    return get_project_tags(request)
VIEWEOF

###############################################################################
# 3. Add URL routes
###############################################################################

python3 << 'PATCH2'
from pathlib import Path

path = Path("hc/api/urls.py")
content = path.read_text()
old = '    path("channels/", views.channels),'
new = '''    path("checks/<uuid:code>/tags/", views.check_tags, name="hc-api-check-tags"),
    path(
        "checks/<uuid:code>/tags/<quoted:tag>/",
        views.single_tag,
        name="hc-api-single-tag",
    ),
    path("tags/", views.project_tags, name="hc-api-project-tags"),
    path("channels/", views.channels),'''
if old not in content:
    raise SystemExit("expected urls insertion point not found")
path.write_text(content.replace(old, new, 1))
PATCH2
