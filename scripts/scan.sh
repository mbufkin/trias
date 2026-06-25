#!/usr/bin/env bash
# Trias passive scan — one mode: static | deps | deploy | all
# Usage: scan.sh static --project /path/to/app
# Active trials: Peira (separate tool). See docs/SECURITY-LANES.md.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="${PYTHON:-python3}"

exec "$PYTHON" -m trias scan "$@"
