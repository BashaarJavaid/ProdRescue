#!/usr/bin/env bash
# Inject a synthetic production crash and poll the pipeline until it finishes.
# Usage: scripts/inject_crash.sh [API_URL]
set -euo pipefail

API="${1:-http://localhost:8000}"

echo "→ POST ${API}/ingest"
RESP=$(curl -sS -X POST "${API}/ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "service": "payments",
    "message": "AttributeError: '"'"'NoneType'"'"' object has no attribute '"'"'total'"'"' in charge()",
    "stacktrace": "Traceback (most recent call last):\n  File \"src/payments/processor.py\", line 22, in charge\n    amount = order.total * 100\nAttributeError: '"'"'NoneType'"'"' object has no attribute '"'"'total'"'"'",
    "occurred_at": "2026-06-16T10:30:00Z",
    "metadata": {"env": "prod", "region": "us-east-1"}
  }')
echo "${RESP}"

TASK_ID=$(echo "${RESP}" | python3 -c "import sys, json; print(json.load(sys.stdin)['task_id'])")
echo "→ task_id=${TASK_ID}; polling ${API}/tasks/${TASK_ID}"

for _ in $(seq 1 60); do
  STATUS=$(curl -sS "${API}/tasks/${TASK_ID}")
  STATE=$(echo "${STATUS}" | python3 -c "import sys, json; print(json.load(sys.stdin)['status'])")
  echo "   status=${STATE}"
  if [ "${STATE}" = "SUCCESS" ] || [ "${STATE}" = "FAILURE" ]; then
    echo "${STATUS}" | python3 -m json.tool
    break
  fi
  sleep 5
done
