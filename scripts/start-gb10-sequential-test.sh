#!/usr/bin/env bash
# Start sequential file-by-file Trias test on GB10 (sync + submit in background).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PDF="${PDF_FILL_JASON:-/Users/michaelbufkin/Documents/Coding/devhub/tools/pdf-fill-jason}"
GB10_SH="$ROOT/scripts/gb10-ssh.sh"
LOG_LOCAL="$ROOT/results/gb10-sequential-test.log"

chmod +x "$GB10_SH"
export RSYNC_RSH="$("$GB10_SH" --rsync-rsh)"

echo "=== Sync Trias ===" | tee -a "$LOG_LOCAL"
bash "$ROOT/scripts/sync-to-gb10.sh" 2>&1 | tee -a "$LOG_LOCAL"

echo "=== Sync Travel PDF app/ ===" | tee -a "$LOG_LOCAL"
rsync -av --exclude '__pycache__' --exclude '*.pyc' \
  "$PDF/app/" "lenovo@100.85.15.59:/home/lenovo/pdf-fill-jason/app/" 2>&1 | tee -a "$LOG_LOCAL"

"$GB10_SH" 'test -f ~/pdf-fill-jason/app/security.py'

echo "=== Restart worker ===" | tee -a "$LOG_LOCAL"
"$GB10_SH" 'systemctl --user restart trias; sleep 2; systemctl --user is-active trias'

echo "=== Launch submit (background on GB10) ===" | tee -a "$LOG_LOCAL"
"$GB10_SH" 'nohup bash -c "
set -euo pipefail
cd /home/lenovo/pdf-fill-jason
~/.local/bin/trias submit --focus security --wait --timeout 5400 \
  app/security.py app/auth.py app/csrf.py \
  2>&1 | tee /tmp/trias-gb10-sequential-test.log
" >> /tmp/trias-gb10-sequential-test.nohup 2>&1 & echo started_pid=$!'

sleep 4
"$GB10_SH" 'grep -E "^Submitted:|^Review:" /tmp/trias-gb10-sequential-test.log 2>/dev/null | head -5; tail -5 /tmp/trias-gb10-sequential-test.log 2>/dev/null || true'

echo "Monitor: $GB10_SH 'tail -f /tmp/trias-gb10-sequential-test.log'"
echo "Status:  $GB10_SH 'trias status'"
