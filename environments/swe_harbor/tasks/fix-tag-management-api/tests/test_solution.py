"""Tests for the tag-management debug/fix task."""
from __future__ import annotations

import json
import os
import sys
import uuid
from urllib.parse import quote

sys.path.insert(0, "/app")
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hc.settings")
django.setup()

from django.utils.timezone import now

from hc.api.models import Check
from hc.test import BaseTestCase


def assert_json_error(testcase, response, status_code: int, expected_error: str):
    testcase.assertEqual(response.status_code, status_code)
    testcase.assertEqual(response.get("Content-Type"), "application/json")
    testcase.assertEqual(response.json()["error"], expected_error)


class TagHelperModelTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(
            project=self.project,
            name="Tag Helpers",
            tags=" alpha   beta alpha   gamma  ",
        )

    def test_clean_tags_deduplicates_and_preserves_order(self):
        self.assertEqual(self.check.clean_tags(), ["alpha", "beta", "gamma"])

    def test_add_tag_to_empty_does_not_introduce_leading_space(self):
        check = Check.objects.create(project=self.project, name="Empty", tags="")
        changed = check.add_tag("deploy")
        check.refresh_from_db()
        self.assertTrue(changed)
        self.assertEqual(check.tags, "deploy")

    def test_add_tag_returns_false_when_tag_already_exists(self):
        changed = self.check.add_tag("alpha")
        self.check.refresh_from_db()
        self.assertFalse(changed)
        self.assertEqual(self.check.tags, " alpha   beta alpha   gamma  ")

    def test_remove_tag_returns_true_and_updates_tags(self):
        changed = self.check.remove_tag("beta")
        self.check.refresh_from_db()
        self.assertTrue(changed)
        self.assertEqual(self.check.tags, "alpha gamma")

    def test_remove_tag_returns_false_when_missing(self):
        changed = self.check.remove_tag("nope")
        self.assertFalse(changed)


class CheckTagsApiTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(
            project=self.project,
            name="One",
            tags="alpha   beta alpha",
        )
        self.url = f"/api/v3/checks/{self.check.code}/tags/"

    def test_list_tags_returns_normalized_list(self):
        r = self.client.get(self.url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["tags"], ["alpha", "beta"])

    def test_list_tags_forbidden_for_other_project(self):
        other = Check.objects.create(project=self.bobs_project, name="Bob")
        url = f"/api/v3/checks/{other.code}/tags/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 403)

    def test_list_tags_not_found(self):
        url = f"/api/v3/checks/{uuid.uuid4()}/tags/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 404)

    def test_list_tags_wrong_api_key(self):
        r = self.client.get(self.url, HTTP_X_API_KEY="Y" * 32)
        self.assertEqual(r.status_code, 401)


class AddTagApiTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Add", tags="alpha")

    def post(self, tag: str, api_key: str = "X" * 32):
        url = f"/api/v3/checks/{self.check.code}/tags/{tag}/"
        return self.client.post(
            url,
            json.dumps({"api_key": api_key}),
            content_type="application/json",
            HTTP_X_API_KEY=api_key,
        )

    def test_add_new_tag_returns_201(self):
        r = self.post("beta")
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["added"])
        self.assertEqual(r.json()["tags"], ["alpha", "beta"])

    def test_add_existing_tag_returns_200(self):
        r = self.post("alpha")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["added"])
        self.assertEqual(r.json()["tags"], ["alpha"])

    def test_add_invalid_tag_with_space(self):
        r = self.post("bad%25tag")
        assert_json_error(self, r, 400, "invalid tag")

    def test_add_invalid_tag_with_symbol(self):
        r = self.post("%25")
        assert_json_error(self, r, 400, "invalid tag")

    def test_add_invalid_tag_too_long(self):
        r = self.post("x" * 51)
        assert_json_error(self, r, 400, "invalid tag")

    def test_add_forbidden_for_other_project(self):
        other = Check.objects.create(project=self.bobs_project, name="Bob")
        url = f"/api/v3/checks/{other.code}/tags/deploy/"
        r = self.client.post(
            url,
            json.dumps({"api_key": "X" * 32}),
            content_type="application/json",
            HTTP_X_API_KEY="X" * 32,
        )
        self.assertEqual(r.status_code, 403)

    def test_add_not_found(self):
        url = f"/api/v3/checks/{uuid.uuid4()}/tags/deploy/"
        r = self.client.post(
            url,
            json.dumps({"api_key": "X" * 32}),
            content_type="application/json",
            HTTP_X_API_KEY="X" * 32,
        )
        self.assertEqual(r.status_code, 404)

    def test_add_wrong_api_key(self):
        r = self.post("deploy", api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)

    def test_add_rejects_more_than_20_tags(self):
        tags = [f"t{i}" for i in range(20)]
        self.check.tags = " ".join(tags)
        self.check.save(update_fields=["tags"])
        r = self.post("newtag")
        assert_json_error(self, r, 400, "too many tags")

    def test_add_rejects_result_longer_than_500_chars(self):
        tags = [f"t{i}{'x' * 47}" for i in range(10)]
        # joined length is 499 chars, adding another tag would exceed 500
        self.check.tags = " ".join(tags)
        self.check.save(update_fields=["tags"])
        r = self.post("z")
        assert_json_error(self, r, 400, "tags field is too long")

    def test_add_supports_url_encoded_tag(self):
        encoded = quote("v1~blue", safe="")
        r = self.post(encoded)
        self.assertEqual(r.status_code, 201)
        self.assertIn("v1~blue", r.json()["tags"])


class RemoveTagApiTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Remove", tags="alpha beta")

    def delete(self, tag: str, api_key: str = "X" * 32):
        url = f"/api/v3/checks/{self.check.code}/tags/{tag}/"
        return self.client.delete(url, HTTP_X_API_KEY=api_key)

    def test_remove_existing_tag_returns_204(self):
        r = self.delete("beta")
        self.assertEqual(r.status_code, 204)
        self.check.refresh_from_db()
        self.assertEqual(self.check.tags, "alpha")

    def test_remove_missing_tag_returns_404(self):
        r = self.delete("missing")
        assert_json_error(self, r, 404, "tag not found")

    def test_remove_invalid_tag(self):
        r = self.delete("%25")
        assert_json_error(self, r, 400, "invalid tag")

    def test_remove_forbidden_for_other_project(self):
        other = Check.objects.create(project=self.bobs_project, name="Bob", tags="alpha")
        url = f"/api/v3/checks/{other.code}/tags/alpha/"
        r = self.client.delete(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 403)

    def test_remove_not_found(self):
        url = f"/api/v3/checks/{uuid.uuid4()}/tags/alpha/"
        r = self.client.delete(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 404)

    def test_remove_wrong_api_key(self):
        r = self.delete("alpha", api_key="Y" * 32)
        self.assertEqual(r.status_code, 401)

    def test_remove_supports_url_encoded_tag(self):
        self.check.tags = "v1~blue alpha"
        self.check.save(update_fields=["tags"])
        encoded = quote("v1~blue", safe="")
        r = self.delete(encoded)
        self.assertEqual(r.status_code, 204)
        self.check.refresh_from_db()
        self.assertEqual(self.check.tags, "alpha")


class ProjectTagsApiTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        Check.objects.create(project=self.project, name="A", tags="alpha beta")
        Check.objects.create(project=self.project, name="B", tags="beta gamma gamma")
        Check.objects.create(project=self.project, name="C", tags="")
        Check.objects.create(project=self.bobs_project, name="Other", tags="omega")
        self.url = "/api/v3/tags/"

    def test_project_tags_returns_counts_sorted(self):
        r = self.client.get(self.url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.json()["tags"],
            [
                {"name": "alpha", "count": 1},
                {"name": "beta", "count": 2},
                {"name": "gamma", "count": 1},
            ],
        )

    def test_project_tags_no_cross_project_leak(self):
        r = self.client.get(self.url, HTTP_X_API_KEY="X" * 32)
        names = [item["name"] for item in r.json()["tags"]]
        self.assertNotIn("omega", names)

    def test_project_tags_prefix_filter(self):
        r = self.client.get(self.url + "?prefix=b", HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["tags"], [{"name": "beta", "count": 2}])

    def test_project_tags_wrong_api_key(self):
        r = self.client.get(self.url, HTTP_X_API_KEY="Y" * 32)
        self.assertEqual(r.status_code, 401)


class TagRoutesAcrossVersionsTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Route", tags="alpha")

    def test_v1_check_tags_route(self):
        url = f"/api/v1/checks/{self.check.code}/tags/"
        r = self.client.get(url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

    def test_v2_add_tag_route(self):
        url = f"/api/v2/checks/{self.check.code}/tags/beta/"
        r = self.client.post(
            url,
            json.dumps({"api_key": "X" * 32}),
            content_type="application/json",
            HTTP_X_API_KEY="X" * 32,
        )
        self.assertEqual(r.status_code, 201)

    def test_v3_project_tags_route(self):
        r = self.client.get("/api/v3/tags/", HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)


class TagLifecycleIntegrationTestCase(BaseTestCase):
    """Checks add/remove/re-add behavior and aggregate updates."""

    def setUp(self):
        super().setUp()
        self.check = Check.objects.create(project=self.project, name="Life", tags="alpha")

    def post(self, tag: str):
        return self.client.post(
            f"/api/v3/checks/{self.check.code}/tags/{tag}/",
            json.dumps({"api_key": "X" * 32}),
            content_type="application/json",
            HTTP_X_API_KEY="X" * 32,
        )

    def delete(self, tag: str):
        return self.client.delete(
            f"/api/v3/checks/{self.check.code}/tags/{tag}/",
            HTTP_X_API_KEY="X" * 32,
        )

    def test_add_remove_readd_updates_counts_without_duplicates(self):
        self.assertEqual(self.post("deploy").status_code, 201)
        self.assertEqual(self.delete("deploy").status_code, 204)
        self.assertEqual(self.post("deploy").status_code, 201)
        self.assertEqual(self.post("deploy").status_code, 200)

        self.check.refresh_from_db()
        self.assertEqual(self.check.tags, "alpha deploy")

        tags = self.client.get("/api/v3/tags/", HTTP_X_API_KEY="X" * 32).json()["tags"]
        self.assertEqual(tags, [{"name": "alpha", "count": 1}, {"name": "deploy", "count": 1}])
