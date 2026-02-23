"""Tests for the Project Maintenance Windows feature."""
from __future__ import annotations

import json
import uuid
from datetime import timedelta as td

from django.test.utils import override_settings
from django.utils.timezone import now

import os
import sys
sys.path.insert(0, "/app")
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hc.settings")
django.setup()

from hc.api.models import Check
from hc.test import BaseTestCase


class MaintenanceWindowModelTestCase(BaseTestCase):
    """Tests for the MaintenanceWindow model itself."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Test Check")

    def test_create_window(self):
        """Can create a maintenance window linked to a project."""
        from hc.api.models import MaintenanceWindow
        w = MaintenanceWindow.objects.create(
            project=self.project,
            title="Server upgrade",
            start_time=now(),
            end_time=now() + td(hours=2),
        )
        self.assertIsNotNone(w.code)
        self.assertEqual(w.title, "Server upgrade")

    def test_to_dict(self):
        """to_dict() returns correct keys and values."""
        from hc.api.models import MaintenanceWindow
        w = MaintenanceWindow.objects.create(
            project=self.project, title="Deploy",
            start_time=now(), end_time=now() + td(hours=1),
        )
        d = w.to_dict()
        self.assertEqual(d["uuid"], str(w.code))
        self.assertEqual(d["title"], "Deploy")
        self.assertIn("start_time", d)
        self.assertIn("end_time", d)
        self.assertIn("created", d)

    def test_is_active_during_window(self):
        """is_active() returns True during the window."""
        from hc.api.models import MaintenanceWindow
        w = MaintenanceWindow.objects.create(
            project=self.project, title="Active",
            start_time=now() - td(hours=1),
            end_time=now() + td(hours=1),
        )
        self.assertTrue(w.is_active())

    def test_is_active_at_start_boundary(self):
        """is_active() returns True at exactly start_time (inclusive)."""
        from hc.api.models import MaintenanceWindow
        t = now()
        w = MaintenanceWindow.objects.create(
            project=self.project, title="Boundary",
            start_time=t, end_time=t + td(hours=1),
        )
        self.assertTrue(w.is_active(at=t))

    def test_is_active_at_end_boundary(self):
        """is_active() returns False at exactly end_time (exclusive)."""
        from hc.api.models import MaintenanceWindow
        t = now()
        w = MaintenanceWindow.objects.create(
            project=self.project, title="Boundary",
            start_time=t - td(hours=1), end_time=t,
        )
        self.assertFalse(w.is_active(at=t))

    def test_cascade_delete(self):
        """Deleting a project deletes its maintenance windows."""
        from hc.api.models import MaintenanceWindow
        project_id = self.bobs_project.id
        MaintenanceWindow.objects.create(
            project=self.bobs_project, title="Will be deleted",
            start_time=now(), end_time=now() + td(hours=1),
        )
        self.assertEqual(
            MaintenanceWindow.objects.filter(project_id=project_id).count(), 1
        )
        self.bobs_project.delete()
        self.assertEqual(
            MaintenanceWindow.objects.filter(project_id=project_id).count(), 0
        )

class CreateMaintenanceWindowApiTestCase(BaseTestCase):
    """Tests for POST /api/v3/maintenance/"""

    def setUp(self):
        super().setUp()
        self.url = "/api/v3/maintenance/"

    def post(self, data, api_key=None):
        if api_key is None:
            api_key = "X" * 32
        return self.client.post(
            self.url,
            json.dumps({**data, "api_key": api_key}),
            content_type="application/json",
        )

    def test_create_window(self):
        """POST should create a maintenance window and return 201."""
        start = (now() + td(hours=1)).isoformat()
        end = (now() + td(hours=3)).isoformat()
        r = self.post({"title": "Server upgrade", "start_time": start, "end_time": end})
        self.assertEqual(r.status_code, 201)
        doc = r.json()
        self.assertEqual(doc["title"], "Server upgrade")
        self.assertIn("uuid", doc)
        self.assertIn("start_time", doc)
        self.assertIn("end_time", doc)

    def test_missing_title(self):
        """POST without title should return 400."""
        start = (now() + td(hours=1)).isoformat()
        end = (now() + td(hours=2)).isoformat()
        r = self.post({"start_time": start, "end_time": end})
        self.assertEqual(r.status_code, 400)

    def test_empty_title(self):
        """POST with empty title should return 400."""
        start = (now() + td(hours=1)).isoformat()
        end = (now() + td(hours=2)).isoformat()
        r = self.post({"title": "   ", "start_time": start, "end_time": end})
        self.assertEqual(r.status_code, 400)

    def test_title_too_long(self):
        """POST with title > 100 chars should return 400."""
        start = (now() + td(hours=1)).isoformat()
        end = (now() + td(hours=2)).isoformat()
        r = self.post({"title": "x" * 101, "start_time": start, "end_time": end})
        self.assertEqual(r.status_code, 400)

    def test_invalid_start_time_format(self):
        """POST with non-ISO start_time should return 400."""
        end = (now() + td(hours=2)).isoformat()
        r = self.post({"title": "Test", "start_time": "not-a-date", "end_time": end})
        self.assertEqual(r.status_code, 400)

    def test_start_after_end(self):
        """POST with start_time > end_time should return 400."""
        start = (now() + td(hours=5)).isoformat()
        end = (now() + td(hours=1)).isoformat()
        r = self.post({"title": "Test", "start_time": start, "end_time": end})
        self.assertEqual(r.status_code, 400)
        self.assertIn("before", r.json()["error"].lower())

    def test_duration_exceeds_7_days(self):
        """POST with window > 7 days should return 400."""
        start = (now() + td(hours=1)).isoformat()
        end = (now() + td(days=8)).isoformat()
        r = self.post({"title": "Long", "start_time": start, "end_time": end})
        self.assertEqual(r.status_code, 400)
        self.assertIn("7 days", r.json()["error"].lower())

    def test_overlapping_windows(self):
        """POST should reject windows that overlap with existing ones."""
        from hc.api.models import MaintenanceWindow
        base = now() + td(hours=1)
        MaintenanceWindow.objects.create(
            project=self.project, title="Existing",
            start_time=base, end_time=base + td(hours=4),
        )
        # Overlapping: starts during existing window
        start = (base + td(hours=1)).isoformat()
        end = (base + td(hours=5)).isoformat()
        r = self.post({"title": "Overlap", "start_time": start, "end_time": end})
        self.assertEqual(r.status_code, 400)
        self.assertIn("overlapping", r.json()["error"].lower())

    def test_adjacent_windows_no_overlap(self):
        """Adjacent (non-overlapping) windows should be allowed."""
        from hc.api.models import MaintenanceWindow
        base = now() + td(hours=1)
        MaintenanceWindow.objects.create(
            project=self.project, title="First",
            start_time=base, end_time=base + td(hours=2),
        )
        # Adjacent: starts exactly when first ends (no overlap due to half-open)
        start = (base + td(hours=2)).isoformat()
        end = (base + td(hours=4)).isoformat()
        r = self.post({"title": "Adjacent", "start_time": start, "end_time": end})
        self.assertEqual(r.status_code, 201)

    def test_max_50_windows(self):
        """POST should return 403 when project has 50 windows."""
        from hc.api.models import MaintenanceWindow
        base = now() + td(days=100)
        for i in range(50):
            MaintenanceWindow.objects.create(
                project=self.project, title=f"Window {i}",
                start_time=base + td(hours=i * 10),
                end_time=base + td(hours=i * 10 + 1),
            )
        start = (now() + td(hours=1)).isoformat()
        end = (now() + td(hours=2)).isoformat()
        r = self.post({"title": "One too many", "start_time": start, "end_time": end})
        self.assertEqual(r.status_code, 403)
        self.assertIn("too many", r.json()["error"].lower())

class ListMaintenanceWindowsApiTestCase(BaseTestCase):
    """Tests for GET /api/v3/maintenance/"""

    def setUp(self):
        super().setUp()
        self.url = "/api/v3/maintenance/"

    def get(self, params="", api_key=None):
        if api_key is None:
            api_key = "X" * 32
        url = self.url
        if params:
            url += "?" + params
        return self.client.get(url, HTTP_X_API_KEY=api_key)

    def test_list_empty(self):
        """GET should return empty list when no windows exist."""
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["windows"], [])

    def test_list_windows(self):
        """GET should return all windows for the project."""
        from hc.api.models import MaintenanceWindow
        MaintenanceWindow.objects.create(
            project=self.project, title="A",
            start_time=now(), end_time=now() + td(hours=1),
        )
        MaintenanceWindow.objects.create(
            project=self.project, title="B",
            start_time=now() + td(hours=2), end_time=now() + td(hours=3),
        )
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["windows"]), 2)

    def test_list_does_not_include_other_projects(self):
        """GET should only return windows for the authenticated project."""
        from hc.api.models import MaintenanceWindow
        MaintenanceWindow.objects.create(
            project=self.project, title="Mine",
            start_time=now(), end_time=now() + td(hours=1),
        )
        MaintenanceWindow.objects.create(
            project=self.bobs_project, title="Bob's",
            start_time=now(), end_time=now() + td(hours=1),
        )
        r = self.get()
        windows = r.json()["windows"]
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["title"], "Mine")

    def test_filter_active(self):
        """GET with ?active=true should only return active windows."""
        from hc.api.models import MaintenanceWindow
        MaintenanceWindow.objects.create(
            project=self.project, title="Active",
            start_time=now() - td(hours=1),
            end_time=now() + td(hours=1),
        )
        MaintenanceWindow.objects.create(
            project=self.project, title="Future",
            start_time=now() + td(days=1),
            end_time=now() + td(days=1, hours=2),
        )
        r = self.get("active=true")
        windows = r.json()["windows"]
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["title"], "Active")

    def test_wrong_api_key(self):
        """GET with wrong API key should return 401."""
        r = self.get(api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)


class DeleteMaintenanceWindowApiTestCase(BaseTestCase):
    """Tests for DELETE /api/v3/maintenance/<uuid>/"""

    def setUp(self):
        super().setUp()
        from hc.api.models import MaintenanceWindow
        self.window = MaintenanceWindow.objects.create(
            project=self.project, title="To Delete",
            start_time=now() + td(hours=1),
            end_time=now() + td(hours=2),
        )
        self.url = f"/api/v3/maintenance/{self.window.code}/"

    def test_delete_window(self):
        """DELETE should remove the window and return 204."""
        from hc.api.models import MaintenanceWindow
        r = self.client.delete(self.url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(
            MaintenanceWindow.objects.filter(code=self.window.code).count(), 0
        )

    def test_wrong_project(self):
        """DELETE for a window in a different project should return 403."""
        from hc.api.models import MaintenanceWindow
        other_window = MaintenanceWindow.objects.create(
            project=self.bobs_project, title="Bob's",
            start_time=now(), end_time=now() + td(hours=1),
        )
        url = f"/api/v3/maintenance/{other_window.code}/"
        r = self.client.delete(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 403)

    def test_nonexistent_window(self):
        """DELETE for a nonexistent window should return 404."""
        url = f"/api/v3/maintenance/{uuid.uuid4()}/"
        r = self.client.delete(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 404)

    def test_wrong_api_key(self):
        """DELETE with wrong API key should return 401."""
        r = self.client.delete(self.url, HTTP_X_API_KEY="Y" * 32)
        self.assertEqual(r.status_code, 401)


class CheckStatusMaintenanceTestCase(BaseTestCase):
    """Tests that maintenance windows correctly affect Check.get_status()."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(
            project=self.project, name="Test Check", status="up", last_ping=now()
        )

    def test_status_maintenance_during_active_window(self):
        """get_status() should return 'maintenance' when an active window exists."""
        from hc.api.models import MaintenanceWindow
        MaintenanceWindow.objects.create(
            project=self.project, title="Active",
            start_time=now() - td(hours=1),
            end_time=now() + td(hours=1),
        )
        self.assertEqual(self.check.get_status(), "maintenance")

    def test_status_normal_when_no_window(self):
        """get_status() returns normal status when no maintenance window is active."""
        self.assertEqual(self.check.get_status(), "up")

    def test_status_normal_when_window_is_future(self):
        """get_status() returns normal status when window hasn't started yet."""
        from hc.api.models import MaintenanceWindow
        MaintenanceWindow.objects.create(
            project=self.project, title="Future",
            start_time=now() + td(hours=1),
            end_time=now() + td(hours=2),
        )
        self.assertEqual(self.check.get_status(), "up")

    def test_status_normal_when_window_is_past(self):
        """get_status() returns normal status when window has ended."""
        from hc.api.models import MaintenanceWindow
        MaintenanceWindow.objects.create(
            project=self.project, title="Past",
            start_time=now() - td(hours=2),
            end_time=now() - td(hours=1),
        )
        self.assertEqual(self.check.get_status(), "up")

    def test_paused_overrides_maintenance(self):
        """Paused status should not be overridden by maintenance."""
        from hc.api.models import MaintenanceWindow
        self.check.status = "paused"
        self.check.save()
        MaintenanceWindow.objects.create(
            project=self.project, title="Active",
            start_time=now() - td(hours=1),
            end_time=now() + td(hours=1),
        )
        self.assertEqual(self.check.get_status(), "paused")

    def test_new_overrides_maintenance(self):
        """New status should not be overridden by maintenance."""
        from hc.api.models import MaintenanceWindow
        self.check.status = "new"
        self.check.save()
        MaintenanceWindow.objects.create(
            project=self.project, title="Active",
            start_time=now() - td(hours=1),
            end_time=now() + td(hours=1),
        )
        self.assertEqual(self.check.get_status(), "new")

    def test_maintenance_overrides_down(self):
        """Down status should be overridden by maintenance."""
        from hc.api.models import MaintenanceWindow
        self.check.status = "down"
        self.check.save()
        MaintenanceWindow.objects.create(
            project=self.project, title="Active",
            start_time=now() - td(hours=1),
            end_time=now() + td(hours=1),
        )
        self.assertEqual(self.check.get_status(), "maintenance")

    def test_in_maintenance_true_in_to_dict(self):
        """to_dict() should include in_maintenance=True during active window."""
        from hc.api.models import MaintenanceWindow
        MaintenanceWindow.objects.create(
            project=self.project, title="Active",
            start_time=now() - td(hours=1),
            end_time=now() + td(hours=1),
        )
        d = self.check.to_dict()
        self.assertIn("in_maintenance", d)
        self.assertTrue(d["in_maintenance"])

    def test_in_maintenance_false_in_to_dict(self):
        """to_dict() should include in_maintenance=False when no active window."""
        d = self.check.to_dict()
        self.assertIn("in_maintenance", d)
        self.assertFalse(d["in_maintenance"])

    def test_in_maintenance_true_even_when_paused(self):
        """in_maintenance should be True for paused checks during a window."""
        from hc.api.models import MaintenanceWindow
        self.check.status = "paused"
        self.check.save()
        MaintenanceWindow.objects.create(
            project=self.project, title="Active",
            start_time=now() - td(hours=1),
            end_time=now() + td(hours=1),
        )
        d = self.check.to_dict()
        self.assertTrue(d["in_maintenance"])
        self.assertEqual(d["status"], "paused")


class MaintenanceUrlRoutingTestCase(BaseTestCase):
    """Tests that URL routing works for all API versions."""

    def test_v1_list_endpoint(self):
        """The maintenance endpoint should work under /api/v1/."""
        r = self.client.get("/api/v1/maintenance/", HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

    def test_v2_list_endpoint(self):
        """The maintenance endpoint should work under /api/v2/."""
        r = self.client.get("/api/v2/maintenance/", HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

    def test_v3_list_endpoint(self):
        """The maintenance endpoint should work under /api/v3/."""
        r = self.client.get("/api/v3/maintenance/", HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

    def test_options_request(self):
        """OPTIONS should return 204 with CORS headers."""
        r = self.client.options("/api/v3/maintenance/")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r["Access-Control-Allow-Origin"], "*")
