#!/usr/bin/env bash
# Sync Trias source to GB10 (Lenovo PGX) for worker + review tests.
# Requires: Tailscale + SOCKS (ssh config Host gb10 → ProxyCommand localhost:1055)
#
# Usage:
#   ./scripts/sync-to-gb10.sh
#   GB10_HOST=gb10 GB10_TRIAS_DIR=/home/lenovo/tools/trias ./scripts/sync-to-gb10.sh
set -euo pipefail

GB10="${GB10_HOST:-gb10}"
REMOTE="${GB10_TRIAS_DIR:-/home/lenovo/tools/trias}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GB10_SH="$ROOT/scripts/gb10-ssh.sh"

ssh_gb10() {
  if ssh -o ConnectTimeout=10 "$GB10" true 2>/dev/null; then
    ssh -o ConnectTimeout=15 "$GB10" "$@"
  elif [[ -x "$GB10_SH" ]]; then
    "$GB10_SH" "$@"
  else
    echo "error: cannot reach GB10 (start Tailscale or install $GB10_SH)" >&2
    return 1
  fi
}

rsync_gb10() {
  if ssh -o ConnectTimeout=10 "$GB10" true 2>/dev/null; then
    rsync "$@" "$GB10:$REMOTE/"
  elif [[ -x "$GB10_SH" ]]; then
    export RSYNC_RSH="$("$GB10_SH" --rsync-rsh)"
    rsync "$@" "lenovo@100.85.15.59:$REMOTE/"
  else
    echo "error: cannot reach GB10" >&2
    return 1
  fi
}

RSYNC_EXCLUDES=(
  --exclude '.venv'
  --exclude '__pycache__'
  --exclude '*.pyc'
  --exclude '.pytest_cache'
  --exclude '.git'
  --exclude 'results/*.md'
  --exclude '.DS_Store'
)

echo "Checking SSH to ${GB10}..."
ssh_gb10 "mkdir -p '$REMOTE'"

echo "Syncing Trias → GB10:${REMOTE} ..."
rsync_gb10 -av --delete "${RSYNC_EXCLUDES[@]}" \
  "$ROOT/pyproject.toml" \
  "$ROOT/README.md" \
  "$ROOT/config.example.yaml" \
  "$ROOT/src" \
  "$ROOT/scripts" \
  "$ROOT/docs" \
  "$ROOT/systemd"

echo "Installing editable Trias on GB10 (user site) ..."
ssh_gb10 bash -s <<EOF
set -euo pipefail
cd '$REMOTE'
python3 -m pip install -e . --user --break-system-packages 2>/dev/null \
  || python3 -m pip install -e . --user
echo "trias: \$(command -v trias || echo missing)"
trias scan static --help >/dev/null 2>&1 || PYTHONPATH='$REMOTE/src' python3 -m trias scan static --help >/dev/null
echo "OK — trias CLI reachable on GB10"
EOF

echo "Done. Trias at GB10:${REMOTE}"
