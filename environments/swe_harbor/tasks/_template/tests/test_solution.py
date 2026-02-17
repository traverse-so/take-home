# TODO: Write pytest test cases that verify the solution.
#
# All tests run against the Healthchecks Django app at /app.
#
# Tips:
#   - Extend BaseTestCase for pre-built users/projects/API keys
#   - Use descriptive test names (test_empty_input, test_duplicate_values, etc.)
#   - Include informative assertion messages
#   - Test the happy path, edge cases, and error conditions
#   - Keep tests independent (no shared mutable state)
#   - Aim for 20-40 tests

import os
import sys
sys.path.insert(0, "/app")
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hc.settings")
django.setup()

from hc.test import BaseTestCase


class PlaceholderTestCase(BaseTestCase):
    def test_placeholder(self):
        self.fail("Replace this with your actual tests")
