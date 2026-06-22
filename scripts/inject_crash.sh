#!/usr/bin/env bash
# Inject a synthetic production crash (from a JSON body file) and poll until done.
# Usage: scripts/inject_crash.sh [crashfile.json] [API_URL]
#   crashfile.json  body to POST (default: scripts/crashes/01_payments_none.json)
#   API_URL         ingest endpoint (default: http://localhost:8000)
set -euo pipefail

BODY_FILE="${1:-scripts/crashes/01_payments_none.json}"
API="${2:-http://localhost:8000}"

[ -f "${BODY_FILE}" ] || { echo "no such crash file: ${BODY_FILE}" >&2; exit 1; }

echo "→ POST ${API}/ingest  (body: ${BODY_FILE})"
RESP=$(curl -sS -X POST "${API}/ingest" \
  -H "Content-Type: application/json" \
  ${INGEST_API_KEY:+-H "X-API-Key: ${INGEST_API_KEY}"} \
  -d @"${BODY_FILE}")
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
