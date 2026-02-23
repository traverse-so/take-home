#!/bin/bash
set -e

###############################################################################
# Bootstrap minimal hc.logs app required by hc.settings
###############################################################################

mkdir -p /app/hc/logs
cat > /app/hc/logs/__init__.py << 'PYEOF'
import logging


class Handler(logging.Handler):
    def emit(self, record):
        return
PYEOF

###############################################################################
# 1. Add the MaintenanceWindow model to hc/api/models.py
###############################################################################

cat >> /app/hc/api/models.py << 'PYEOF'


class MaintenanceWindow(models.Model):
    code = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    project = models.ForeignKey(
        "accounts.Project", models.CASCADE, related_name="maintenance_windows"
    )
    title = models.CharField(max_length=100)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    created = models.DateTimeField(default=now)

    class Meta:
        ordering = ["-created"]

    def is_active(self, at=None):
        if at is None:
            at = now()
        return self.start_time <= at < self.end_time

    def to_dict(self) -> dict:
        return {
            "uuid": str(self.code),
            "title": self.title,
            "start_time": isostring(self.start_time),
            "end_time": isostring(self.end_time),
            "created": isostring(self.created),
        }
PYEOF

###############################################################################
# 2. Modify Check.get_status() — maintenance overrides up/down/grace/started
###############################################################################

cd /app

python3 << 'PATCH1'
with open("hc/api/models.py", "r") as f:
    content = f.read()

old = '''    def get_status(self, *, with_started: bool = False) -> str:
        """Return current status for display."""
        frozen_now = now()

        if self.last_start:
            if frozen_now >= self.last_start + self.grace:
                return "down"
            elif with_started:
                return "started"

        if self.status in ("new", "paused", "down"):
            return self.status

        grace_start = self.get_grace_start(with_started=False)
        if grace_start is None:
            # next elapse is "never", so this check will stay up indefinitely
            return "up"

        grace_end = grace_start + self.grace
        if frozen_now >= grace_end:
            return "down"

        if frozen_now >= grace_start:
            return "grace"

        return "up"'''

new = '''    def get_status(self, *, with_started: bool = False) -> str:
        """Return current status for display."""
        frozen_now = now()

        if self.status in ("new", "paused"):
            return self.status

        # Check for active maintenance window
        if MaintenanceWindow.objects.filter(
            project_id=self.project_id,
            start_time__lte=frozen_now,
            end_time__gt=frozen_now,
        ).exists():
            return "maintenance"

        if self.last_start:
            if frozen_now >= self.last_start + self.grace:
                return "down"
            elif with_started:
                return "started"

        if self.status == "down":
            return self.status

        grace_start = self.get_grace_start(with_started=False)
        if grace_start is None:
            # next elapse is "never", so this check will stay up indefinitely
            return "up"

        grace_end = grace_start + self.grace
        if frozen_now >= grace_end:
            return "down"

        if frozen_now >= grace_start:
            return "grace"

        return "up"'''

content = content.replace(old, new, 1)

with open("hc/api/models.py", "w") as f:
    f.write(content)
PATCH1

###############################################################################
# 3. Add in_maintenance to Check.to_dict()
###############################################################################

python3 << 'PATCH2'
with open("hc/api/models.py", "r") as f:
    content = f.read()

old = '''        if self.last_duration:
            result["last_duration"] = int(self.last_duration.total_seconds())

        if readonly:'''

new = '''        if self.last_duration:
            result["last_duration"] = int(self.last_duration.total_seconds())

        result["in_maintenance"] = MaintenanceWindow.objects.filter(
            project_id=self.project_id,
            start_time__lte=now(),
            end_time__gt=now(),
        ).exists()

        if readonly:'''

content = content.replace(old, new, 1)

with open("hc/api/models.py", "w") as f:
    f.write(content)
PATCH2

###############################################################################
# 4. Add API views for maintenance windows
###############################################################################

cat >> /app/hc/api/views.py << 'VIEWEOF'


@authorize
def create_maintenance_window(request: ApiRequest) -> HttpResponse:
    from hc.api.models import MaintenanceWindow

    title = request.json.get("title", "")
    if not isinstance(title, str) or not title.strip():
        return JsonResponse({"error": "title is required"}, status=400)

    if len(title) > 100:
        return JsonResponse({"error": "title is too long"}, status=400)

    start_time_str = request.json.get("start_time", "")
    end_time_str = request.json.get("end_time", "")

    if not start_time_str:
        return JsonResponse({"error": "start_time is required"}, status=400)

    if not end_time_str:
        return JsonResponse({"error": "end_time is required"}, status=400)

    try:
        start_time = datetime.fromisoformat(str(start_time_str))
    except (ValueError, TypeError):
        return JsonResponse({"error": "invalid start_time format"}, status=400)

    try:
        end_time = datetime.fromisoformat(str(end_time_str))
    except (ValueError, TypeError):
        return JsonResponse({"error": "invalid end_time format"}, status=400)

    if start_time >= end_time:
        return JsonResponse(
            {"error": "start_time must be before end_time"}, status=400
        )

    # Max duration: 7 days
    if (end_time - start_time) > td(days=7):
        return JsonResponse(
            {"error": "maintenance window cannot exceed 7 days"}, status=400
        )

    # Max 50 windows per project
    if MaintenanceWindow.objects.filter(project=request.project).count() >= 50:
        return JsonResponse(
            {"error": "too many maintenance windows"}, status=403
        )

    # Check for overlapping windows
    overlap = MaintenanceWindow.objects.filter(
        project=request.project,
        start_time__lt=end_time,
        end_time__gt=start_time,
    ).exists()
    if overlap:
        return JsonResponse(
            {"error": "overlapping maintenance window"}, status=400
        )

    window = MaintenanceWindow(
        project=request.project,
        title=title.strip(),
        start_time=start_time,
        end_time=end_time,
    )
    window.save()

    return JsonResponse(window.to_dict(), status=201)


@authorize_read
def list_maintenance_windows(request: ApiRequest) -> HttpResponse:
    from hc.api.models import MaintenanceWindow

    q = MaintenanceWindow.objects.filter(project=request.project)

    if request.GET.get("active") == "true":
        frozen_now = now()
        q = q.filter(start_time__lte=frozen_now, end_time__gt=frozen_now)

    return JsonResponse({"windows": [w.to_dict() for w in q]})


@cors("DELETE")
@csrf_exempt
@authorize
def delete_maintenance_window(request: ApiRequest, code: UUID) -> HttpResponse:
    from hc.api.models import MaintenanceWindow

    window = get_object_or_404(MaintenanceWindow, code=code)
    if window.project_id != request.project.id:
        return HttpResponseForbidden()

    window.delete()
    return HttpResponse(status=204)


@csrf_exempt
@cors("GET", "POST")
def maintenance(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        return create_maintenance_window(request)
    return list_maintenance_windows(request)
VIEWEOF

###############################################################################
# 5. Add URL routes
###############################################################################

python3 << 'PATCH3'
with open("hc/api/urls.py", "r") as f:
    content = f.read()

old = '    path("channels/", views.channels),'

new = '''    path("maintenance/", views.maintenance, name="hc-api-maintenance"),
    path(
        "maintenance/<uuid:code>/",
        views.delete_maintenance_window,
        name="hc-api-maintenance-delete",
    ),
    path("channels/", views.channels),'''

content = content.replace(old, new, 1)

with open("hc/api/urls.py", "w") as f:
    f.write(content)
PATCH3

###############################################################################
# 6. Create the migration and apply
###############################################################################

cd /app
python manage.py makemigrations api --name maintenancewindow 2>&1
python manage.py migrate 2>&1
