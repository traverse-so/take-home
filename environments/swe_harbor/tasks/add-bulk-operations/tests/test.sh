#!/bin/bash
cd /app

# Bootstrap minimal hc.logs app required by hc.settings
mkdir -p /app/hc/logs
cat > /app/hc/logs/__init__.py << 'PYEOF'
import logging


class Handler(logging.Handler):
    def emit(self, record):
        return
PYEOF

pip install pytest > /dev/null 2>&1

mkdir -p /logs/verifier

# Run migrations in case the solution created new ones
python manage.py migrate --run-syncdb > /dev/null 2>&1

PYTHONPATH=/app DJANGO_SETTINGS_MODULE=hc.settings pytest /tests/test_solution.py -v 2>&1

if [ $? -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
