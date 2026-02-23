"""Tests for the bulk check operations API."""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import timedelta as td

sys.path.insert(0, "/app")
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hc.settings")
django.setup()

from django.utils.timezone import now

from hc.api.models import Check, Flip
from hc.test import BaseTestCase


class BulkTagHelperModelTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Taggy", tags="alpha beta")

    def test_bulk_tags_add_appends_new_tags(self):
        self.check.bulk_tags_add(["gamma", "delta"])
        self.check.refresh_from_db()
        self.assertEqual(self.check.tags, "alpha beta gamma delta")

    def test_bulk_tags_add_deduplicates_existing_tags(self):
        self.check.bulk_tags_add(["beta", "alpha", "gamma", "gamma"])
        self.check.refresh_from_db()
        self.assertEqual(self.check.tags, "alpha beta gamma")

    def test_bulk_tags_remove_removes_requested_tags(self):
        self.check.bulk_tags_remove(["beta"])
        self.check.refresh_from_db()
        self.assertEqual(self.check.tags, "alpha")

    def test_bulk_tags_remove_ignores_missing_tags(self):
        self.check.bulk_tags_remove(["nope"])
        self.check.refresh_from_db()
        self.assertEqual(self.check.tags, "alpha beta")


class BulkValidationApiTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.url = "/api/v3/checks/bulk/"
        self.check = Check.objects.create(project=self.project, name="One")

    def post(self, payload: dict, api_key: str = "X" * 32):
        body = {**payload, "api_key": api_key}
        return self.client.post(self.url, json.dumps(body), content_type="application/json")

    def test_rejects_invalid_action(self):
        r = self.post({"action": "noop", "checks": [str(self.check.code)]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "invalid action")

    def test_rejects_checks_not_list(self):
        r = self.post({"action": "pause", "checks": "not-a-list"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "checks must be a list")

    def test_rejects_empty_checks(self):
        r = self.post({"action": "pause", "checks": []})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "checks must not be empty")

    def test_rejects_more_than_50_checks(self):
        checks = [str(uuid.uuid4()) for _ in range(51)]
        r = self.post({"action": "pause", "checks": checks})
        self.assertEqual(r.status_code, 400)
        self.assertIn("max 50", r.json()["error"])

    def test_rejects_invalid_uuid(self):
        r = self.post({"action": "pause", "checks": ["not-a-uuid"]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "invalid check uuid")

    def test_rejects_nonexistent_check(self):
        r = self.post({"action": "pause", "checks": [str(uuid.uuid4())]})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["error"], "check not found")

    def test_rejects_check_from_other_project(self):
        other_check = Check.objects.create(project=self.bobs_project, name="Bob")
        r = self.post({"action": "pause", "checks": [str(other_check.code)]})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"], "check does not belong to this project")

    def test_rejects_missing_tags_for_add_tags(self):
        r = self.post({"action": "add_tags", "checks": [str(self.check.code)]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "tags is required")

    def test_rejects_missing_tags_for_remove_tags(self):
        r = self.post({"action": "remove_tags", "checks": [str(self.check.code)], "tags": "  "})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "tags is required")

    def test_wrong_api_key(self):
        r = self.post({"action": "pause", "checks": [str(self.check.code)]}, api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)


class BulkPauseResumeApiTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.url = "/api/v3/checks/bulk/"
        self.c1 = Check.objects.create(project=self.project, name="C1", status="up")
        self.c2 = Check.objects.create(project=self.project, name="C2", status="paused")

    def post(self, payload: dict):
        return self.client.post(
            self.url,
            json.dumps({**payload, "api_key": "X" * 32}),
            content_type="application/json",
        )

    def test_pause_applies_only_to_non_paused_checks(self):
        self.c1.last_start = now()
        self.c1.alert_after = now() + td(hours=1)
        self.c1.save()

        r = self.post({"action": "pause", "checks": [str(self.c1.code), str(self.c2.code)]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["action"], "pause")
        self.assertEqual(r.json()["applied"], 1)

        self.c1.refresh_from_db()
        self.c2.refresh_from_db()
        self.assertEqual(self.c1.status, "paused")
        self.assertIsNone(self.c1.last_start)
        self.assertIsNone(self.c1.alert_after)
        self.assertEqual(self.c2.status, "paused")

    def test_pause_creates_flip_for_applied_checks_only(self):
        before = Flip.objects.count()
        r = self.post({"action": "pause", "checks": [str(self.c1.code), str(self.c2.code)]})
        self.assertEqual(r.status_code, 200)
        after = Flip.objects.count()
        self.assertEqual(after - before, 1)

    def test_resume_applies_only_to_paused_checks(self):
        self.c2.last_start = now()
        self.c2.last_ping = now()
        self.c2.alert_after = now() + td(hours=2)
        self.c2.save()

        r = self.post({"action": "resume", "checks": [str(self.c1.code), str(self.c2.code)]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["action"], "resume")
        self.assertEqual(r.json()["applied"], 1)

        self.c1.refresh_from_db()
        self.c2.refresh_from_db()
        self.assertEqual(self.c1.status, "up")
        self.assertEqual(self.c2.status, "new")
        self.assertIsNone(self.c2.last_start)
        self.assertIsNone(self.c2.last_ping)
        self.assertIsNone(self.c2.alert_after)

    def test_resume_creates_flip_for_resumed_checks_only(self):
        before = Flip.objects.count()
        r = self.post({"action": "resume", "checks": [str(self.c1.code), str(self.c2.code)]})
        self.assertEqual(r.status_code, 200)
        after = Flip.objects.count()
        self.assertEqual(after - before, 1)

    def test_pause_atomicity_on_mixed_ownership(self):
        other_check = Check.objects.create(project=self.bobs_project, name="Other", status="up")
        r = self.post(
            {
                "action": "pause",
                "checks": [str(self.c1.code), str(other_check.code)],
            }
        )
        self.assertEqual(r.status_code, 403)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.status, "up")

    def test_resume_atomicity_on_nonexistent_check(self):
        r = self.post(
            {
                "action": "resume",
                "checks": [str(self.c2.code), str(uuid.uuid4())],
            }
        )
        self.assertEqual(r.status_code, 404)
        self.c2.refresh_from_db()
        self.assertEqual(self.c2.status, "paused")


class BulkDeleteApiTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.url = "/api/v3/checks/bulk/"
        self.c1 = Check.objects.create(project=self.project, name="D1")
        self.c2 = Check.objects.create(project=self.project, name="D2")

    def post(self, payload: dict):
        return self.client.post(
            self.url,
            json.dumps({**payload, "api_key": "X" * 32}),
            content_type="application/json",
        )

    def test_delete_removes_all_checks(self):
        r = self.post({"action": "delete", "checks": [str(self.c1.code), str(self.c2.code)]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["action"], "delete")
        self.assertEqual(r.json()["applied"], 2)
        self.assertFalse(Check.objects.filter(code=self.c1.code).exists())
        self.assertFalse(Check.objects.filter(code=self.c2.code).exists())

    def test_delete_atomicity_on_mixed_ownership(self):
        other = Check.objects.create(project=self.bobs_project, name="Bob")
        r = self.post({"action": "delete", "checks": [str(self.c1.code), str(other.code)]})
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Check.objects.filter(code=self.c1.code).exists())

    def test_delete_atomicity_on_nonexistent_check(self):
        r = self.post({"action": "delete", "checks": [str(self.c1.code), str(uuid.uuid4())]})
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Check.objects.filter(code=self.c1.code).exists())


class BulkTagApiTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.url = "/api/v3/checks/bulk/"
        self.c1 = Check.objects.create(project=self.project, name="T1", tags="alpha beta")
        self.c2 = Check.objects.create(project=self.project, name="T2", tags="beta")

    def post(self, payload: dict):
        return self.client.post(
            self.url,
            json.dumps({**payload, "api_key": "X" * 32}),
            content_type="application/json",
        )

    def test_add_tags_applies_to_all_checks(self):
        r = self.post(
            {
                "action": "add_tags",
                "checks": [str(self.c1.code), str(self.c2.code)],
                "tags": "gamma delta",
            }
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["applied"], 2)
        self.c1.refresh_from_db()
        self.c2.refresh_from_db()
        self.assertEqual(self.c1.tags, "alpha beta gamma delta")
        self.assertEqual(self.c2.tags, "beta gamma delta")

    def test_add_tags_deduplicates(self):
        r = self.post(
            {
                "action": "add_tags",
                "checks": [str(self.c1.code)],
                "tags": "beta alpha gamma",
            }
        )
        self.assertEqual(r.status_code, 200)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.tags, "alpha beta gamma")

    def test_remove_tags(self):
        r = self.post(
            {
                "action": "remove_tags",
                "checks": [str(self.c1.code), str(self.c2.code)],
                "tags": "beta",
            }
        )
        self.assertEqual(r.status_code, 200)
        self.c1.refresh_from_db()
        self.c2.refresh_from_db()
        self.assertEqual(self.c1.tags, "alpha")
        self.assertEqual(self.c2.tags, "")

    def test_remove_tags_missing_values_is_noop(self):
        r = self.post(
            {
                "action": "remove_tags",
                "checks": [str(self.c1.code)],
                "tags": "not-present",
            }
        )
        self.assertEqual(r.status_code, 200)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.tags, "alpha beta")

    def test_add_tags_trims_whitespace(self):
        r = self.post(
            {
                "action": "add_tags",
                "checks": [str(self.c1.code)],
                "tags": "   gamma    delta   ",
            }
        )
        self.assertEqual(r.status_code, 200)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.tags, "alpha beta gamma delta")


class BulkRoutingAcrossVersionsTestCase(BaseTestCase):
    def post(self, path: str):
        check = Check.objects.create(project=self.project, name="Route")
        return self.client.post(
            path,
            json.dumps({"api_key": "X" * 32, "action": "pause", "checks": [str(check.code)]}),
            content_type="application/json",
        )

    def test_v1_route(self):
        r = self.post("/api/v1/checks/bulk/")
        self.assertEqual(r.status_code, 200)

    def test_v2_route(self):
        r = self.post("/api/v2/checks/bulk/")
        self.assertEqual(r.status_code, 200)

    def test_v3_route(self):
        r = self.post("/api/v3/checks/bulk/")
        self.assertEqual(r.status_code, 200)


class BulkMultiStepIntegrationTestCase(BaseTestCase):
    """Runs multiple bulk actions back-to-back to stress state transitions."""

    def setUp(self):
        super().setUp()
        self.url = "/api/v3/checks/bulk/"
        self.c1 = Check.objects.create(project=self.project, name="I1", status="up")
        self.c2 = Check.objects.create(project=self.project, name="I2", status="up")

    def post(self, payload: dict):
        return self.client.post(
            self.url,
            json.dumps({**payload, "api_key": "X" * 32}),
            content_type="application/json",
        )

    def test_pause_then_tag_then_resume(self):
        pause = self.post({"action": "pause", "checks": [str(self.c1.code), str(self.c2.code)]})
        self.assertEqual(pause.status_code, 200)
        self.assertEqual(pause.json()["applied"], 2)

        add_tags = self.post(
            {
                "action": "add_tags",
                "checks": [str(self.c1.code), str(self.c2.code)],
                "tags": "prod deploy",
            }
        )
        self.assertEqual(add_tags.status_code, 200)

        resume = self.post({"action": "resume", "checks": [str(self.c1.code), str(self.c2.code)]})
        self.assertEqual(resume.status_code, 200)
        self.assertEqual(resume.json()["applied"], 2)

        self.c1.refresh_from_db()
        self.c2.refresh_from_db()
        self.assertEqual(self.c1.status, "new")
        self.assertEqual(self.c2.status, "new")
        self.assertEqual(self.c1.tags, "prod deploy")
        self.assertEqual(self.c2.tags, "prod deploy")
