#!/bin/bash
# TODO: Write the reference solution.
# This script runs inside the container at /app against the Healthchecks codebase.
# It should produce the correct solution that passes all tests.
#
# Common patterns:
#   - Append to a file:     cat >> /app/hc/api/models.py << 'EOF' ... EOF
#   - Patch a file inline:  python3 -c "..." (read, replace, write)
#   - Run migrations:       cd /app && python manage.py makemigrations api && python manage.py migrate
#   - Install a package:    pip install some-package
