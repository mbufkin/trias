#!/usr/bin/env bash
# End-to-end GB10 test: sync Trias, restart worker, run sequential file-by-file
# security review on Travel PDF auth/security modules, pull report to Mac.
#
# Prerequisites:
#   - Tailscale + SOCKS (ssh gb10 works)
#   - Ollama + council models on GB10
#   - pdf-fill-jason already on GB10 (run pdf-fill-jason/deploy/sync-to-gb10.sh first)
#
# Usage:
#   ./scripts/test-gb10-file-review.sh
#   ./scripts/test-gb10-file-review.sh --no-sync   # skip trias rsync if already deployed
set -euo pipefail

GB10="${GB10_HOST:-gb10}"
TRIAS_REMOTE_DIR="${GB10_TRIAS_DIR:-/home/lenovo/tools/trias}"
PDF_REMOTE="${GB10_PDF_DIR:-/home/lenovo/pdf-fill-jason}"
LOCAL_TRIAS="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_RESULTS="$LOCAL_TRIAS/results"
SYNC_TRIAS=1
TIMEOUT="${TRIAS_TEST_TIMEOUT:-5400}"

for arg in "$@"; do
  case "$arg" in
    --no-sync) SYNC_TRIAS=0 ;;
    -h|--help)
      echo "Usage: $0 [--no-sync]"
      exit 0
      ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done

# Security-critical files — sequential mode = 3 reviewers × N files
TEST_FILES=(
  app/security.py
  app/auth.py
  app/csrf.py
)

echo "=== GB10 Trias file-by-file test ==="
echo "Host: $GB10"
echo "Files: ${TEST_FILES[*]}"
echo "Expected review rounds: $((3 * ${#TEST_FILES[@]})) + synthesis + skeptic"
echo

echo "Step 1 — SSH check ..."
ssh -o ConnectTimeout=15 "$GB10" "hostname && ollama list | head -3"

if [[ "$SYNC_TRIAS" -eq 1 ]]; then
  echo
  echo "Step 2 — sync Trias ..."
  bash "$LOCAL_TRIAS/scripts/sync-to-gb10.sh"
else
  echo
  echo "Step 2 — skip sync (--no-sync)"
fi

echo
echo "Step 3 — restart Trias worker on GB10 ..."
ssh "$GB10" bash -s <<'REMOTE'
set -euo pipefail
if systemctl --user is-active trias >/dev/null 2>&1; then
  systemctl --user restart trias
  sleep 2
  systemctl --user is-active trias
elif pgrep -f 'trias.*worker' >/dev/null; then
  pkill -f 'trias.*worker' || true
  sleep 2
  nohup trias worker >> ~/.trias/worker.log 2>&1 &
  sleep 2
else
  mkdir -p ~/.trias
  nohup trias worker >> ~/.trias/worker.log 2>&1 &
  sleep 2
fi
pgrep -af 'trias.*worker' || { echo "worker failed to start" >&2; exit 1; }
REMOTE

echo
echo "Step 4 — verify Travel PDF paths on GB10 ..."
ssh "$GB10" bash -s <<REMOTE
set -euo pipefail
PDF='$PDF_REMOTE'
for f in ${TEST_FILES[*]}; do
  test -f "\$PDF/\$f" || { echo "missing: \$PDF/\$f — run pdf-fill-jason deploy/sync-to-gb10.sh" >&2; exit 1; }
done
echo "All test files present under \$PDF"
REMOTE

echo
echo "Step 5 — submit sequential security review (runs on GB10, --wait) ..."
echo "This may take 15–45 min depending on model load times."
ssh "$GB10" bash -s <<REMOTE
set -euo pipefail
cd '$PDF_REMOTE'
trias submit --focus security --wait --timeout $TIMEOUT \
  ${TEST_FILES[*]} 2>&1 | tee /tmp/trias-gb10-test.log
REMOTE

TASK_ID=$(ssh "$GB10" "grep '^Submitted:' /tmp/trias-gb10-test.log | awk '{print \$2}' | head -1")

if [[ -z "$TASK_ID" ]]; then
  echo "ERROR: could not parse task id. Check GB10: ssh $GB10 tail -50 /tmp/trias-gb10-test.log" >&2
  exit 1
fi

echo "Task completed: $TASK_ID"

echo
echo "Step 6 — pull report to Mac ..."
mkdir -p "$LOCAL_RESULTS"
export TRIAS_REMOTE="$GB10"
cd "$LOCAL_TRIAS"
PYTHONPATH=src python3 -m trias pull "$TASK_ID" --output "$LOCAL_RESULTS" 2>/dev/null \
  || ssh "$GB10" "cat ~/.trias/results/${TASK_ID}.md" > "$LOCAL_RESULTS/review-${TASK_ID}.md"

REPORT="$LOCAL_RESULTS/review-${TASK_ID}.md"
if [[ ! -f "$REPORT" ]]; then
  # pull may write review-TASK_ID.md without prefix depending on cli
  REPORT=$(ls -t "$LOCAL_RESULTS"/review-"${TASK_ID}"*.md 2>/dev/null | head -1)
fi

if [[ -f "$REPORT" ]]; then
  echo
  echo "=== Report: $REPORT ==="
  head -40 "$REPORT"
  echo
  if grep -q 'file_strategy=sequential' "$REPORT" 2>/dev/null || grep -q 'File coverage' "$REPORT"; then
    echo "OK — sequential file coverage section present"
  else
    echo "WARN — check report for per-file sections (older worker?)"
  fi
  grep -E '^\- (✅|⚠️)' "$REPORT" | head -10 || true
else
  echo "Report not found locally. On GB10: ~/.trias/results/${TASK_ID}.md" >&2
  exit 1
fi

echo
echo "Done. Full report: $REPORT"
echo "Worker log: ssh $GB10 tail -f ~/.trias/worker.log"
