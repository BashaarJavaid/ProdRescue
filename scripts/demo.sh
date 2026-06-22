#!/usr/bin/env bash
# scripts/demo.sh — narrated crash→PR demo, made for recording a GIF/screencast.
#
# It temporarily introduces a real bug into sample_target, runs the autonomous
# pipeline, narrates each stage, then restores the repo (trap, so it restores
# even on Ctrl-C). It records nothing itself — run it inside `asciinema rec`
# or any screen recorder.
#
# For a self-contained demo that opens NO real PRs (reads the local bug, writes
# the PR to ./dryrun_prs/), put the worker in dry-run first:
#     GITHUB_TOKEN= docker compose up -d --force-recreate --no-deps worker
# and switch back afterwards with:
#     docker compose up -d --force-recreate --no-deps worker
set -euo pipefail
cd "$(dirname "$0")/.."

API="${API:-http://localhost:8000}"
FILE="sample_target/src/payments/processor.py"
BACKUP="$(mktemp)"; cp "$FILE" "$BACKUP"
trap 'cp "$BACKUP" "$FILE"; rm -f "$BACKUP"' EXIT INT TERM

set -a; [ -f .env ] && . ./.env; set +a
c(){ printf "\033[%sm%s\033[0m\n" "$1" "$2"; }
pg(){ docker compose exec -T postgres psql -U postgres -d prodrescue -tAc "$1" 2>/dev/null | tr -d ' '; }

# 1) introduce the bug: drop the None-guard in charge()
python3 - "$FILE" <<'PY'
import sys
p=sys.argv[1]; s=open(p).read()
s=s.replace('    if order is None:\n        raise PaymentError("Order not found")\n','')
open(p,'w').write(s)
PY

echo; c "1;31" "🔥 Production crash detected"
python3 -c "import json;d=json.load(open('scripts/crashes/01_payments_none.json'));print('   service:',d['service']);print('   error  :',d['message'])"
echo

docker compose exec -T redis redis-cli FLUSHALL >/dev/null 2>&1 || true   # repeatable

# 2) ingest → dispatch the agent
RESP=$(curl -sS -X POST "$API/ingest" -H "Content-Type: application/json" \
  ${INGEST_API_KEY:+-H "X-API-Key: $INGEST_API_KEY"} -d @scripts/crashes/01_payments_none.json)
TASK=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['task_id'])")
LOG=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin)['log_id'])")
c "1;36" "📥 Ingested — ProdRescue agent dispatched"
echo "   🔍 Triage → 🛠️  Dev → 🐳 QA in an isolated Docker harness"; echo

# 3) narrate each QA attempt as it lands in the DB (shows the self-heal loop live)
seen=0
for _ in $(seq 1 80); do
  sleep 3
  n=$(pg "SELECT count(*) FROM harness_results WHERE log_id='$LOG';"); n=${n:-0}
  while [ "$seen" -lt "$n" ]; do
    seen=$((seen+1))
    ok=$(pg "SELECT passed FROM harness_results WHERE log_id='$LOG' ORDER BY recorded_at LIMIT 1 OFFSET $((seen-1));")
    if [ "$ok" = "t" ]; then c "1;32" "      QA attempt $seen → ✅ tests pass, coverage held"
    else c "1;33" "      QA attempt $seen → ❌ failed — feeding telemetry back to Dev, retrying"; fi
  done
  ST=$(curl -sS -m5 "$API/tasks/$TASK" 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('status',''))" 2>/dev/null || true)
  [ "$ST" = "SUCCESS" ] || [ "$ST" = "FAILURE" ] && break
done

# 4) result — derived from the DB (the /tasks endpoint can return an empty body)
echo
ATT=$(pg "SELECT count(*) FROM harness_results WHERE log_id='$LOG';"); ATT=${ATT:-0}
OKL=$(pg "SELECT passed FROM harness_results WHERE log_id='$LOG' ORDER BY recorded_at DESC LIMIT 1;")
COV=$(pg "SELECT coverage_delta FROM harness_results WHERE log_id='$LOG' ORDER BY recorded_at DESC LIMIT 1;")
DRYFILE="dryrun_prs/prodrescue_${LOG}.md"
if [ "$OKL" = "t" ]; then c "1;32" "✅ Fix written, tested, and shipped — autonomously"
else c "1;33" "• run finished (no PR — see logs)"; fi
echo "   QA attempts : $ATT $([ "$ATT" -gt 1 ] 2>/dev/null && echo '(self-healed on retry)')"
echo "   final QA    : $([ "$OKL" = "t" ] && echo PASS || echo FAIL)    coverage Δ: ${COV:-?}"
if [ -f "$DRYFILE" ]; then
  echo "   pull request: (dry-run) $DRYFILE"
else
  PR=$(curl -sS -m5 "$API/tasks/$TASK" 2>/dev/null | python3 -c "import sys,json;print((json.load(sys.stdin).get('result') or {}).get('pr_url') or '')" 2>/dev/null || true)
  echo "   pull request: ${PR:-https://github.com/${REPO_FULL_NAME:-}/pulls}"
fi
echo; c "1;90" "(sample_target restored to its clean state)"
