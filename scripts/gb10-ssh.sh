#!/usr/bin/env bash
# SSH/rsync to GB10 via userspace tailscaled (when menu-bar SOCKS is down).
set -euo pipefail

TS="${TAILSCALE_BIN:-/Users/michaelbufkin/homebrew/bin/tailscale}"
TSD="${TAILSCALED_BIN:-/Users/michaelbufkin/homebrew/opt/tailscale/bin/tailscaled}"
SOCKET="${TAILSCALE_SOCKET:-/tmp/tailscaled.sock}"
STATE="${TAILSCALE_STATE:-$HOME/.tailscale/tailscaled.state}"

ensure_tailscale() {
  mkdir -p "$(dirname "$STATE")"
  if ! "$TS" --socket="$SOCKET" status >/dev/null 2>&1; then
    pkill -f "tailscaled.*$(basename "$STATE")" 2>/dev/null || true
    sleep 1
    nohup "$TSD" \
      --state="$STATE" \
      --socket="$SOCKET" \
      --tun=userspace-networking \
      >> /tmp/tailscaled-user.log 2>&1 &
    for _ in $(seq 1 20); do
      "$TS" --socket="$SOCKET" status >/dev/null 2>&1 && return 0
      sleep 1
    done
    echo "error: tailscaled did not start (see /tmp/tailscaled-user.log)" >&2
    return 1
  fi
}

ensure_tailscale

GB10_HOST="${GB10_HOST:-lenovo@100.85.15.59}"
SSH_BASE=(ssh -o StrictHostKeyChecking=accept-new -o "ProxyCommand=$TS --socket=$SOCKET nc %h %p")

if [[ "${1:-}" == "--rsync-rsh" ]]; then
  printf 'ssh -o StrictHostKeyChecking=accept-new -o ProxyCommand="%s --socket=%s nc %%h %%p"' "$TS" "$SOCKET"
  exit 0
fi

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 [--rsync-rsh] | remote command ..." >&2
  exit 2
fi

exec "${SSH_BASE[@]}" "$GB10_HOST" "$@"
