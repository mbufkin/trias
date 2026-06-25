# GB10 test — sequential file-by-file review

Run Trias on the **Lenovo ThinkStation PGX** (GB10 GPU) to validate the
new **one-file-at-a-time** council flow on real hardware.

---

## Prerequisites

1. **Tailscale** running on Mac (or `./scripts/gb10-ssh.sh` userspace tailscale)
2. **llama.cpp server** on GB10 — `systemctl --user start llama-cuda@gemma4-31b`
3. **Trias config** — `~/.trias/config.yaml` with `llamacpp.url` (see [LLAMA-CPP.md](LLAMA-CPP.md))
4. **Travel PDF** synced to GB10 (`pdf-fill-jason/deploy/sync-to-gb10.sh`)

---

## One-command test

From the Trias repo on your Mac:

```bash
cd ~/Documents/Coding/devhub/tools/trias
chmod +x scripts/sync-to-gb10.sh scripts/test-gb10-file-review.sh
./scripts/test-gb10-file-review.sh
```

What it does:

| Step | Action |
|------|--------|
| 1 | SSH + Ollama sanity check |
| 2 | Rsync Trias → `gb10:~/tools/trias`, `pip install -e .` |
| 3 | Restart `trias worker` (systemd user service or background) |
| 4 | Confirm `app/security.py`, `app/auth.py`, `app/csrf.py` exist on GB10 |
| 5 | `trias submit --focus security --wait` **on GB10** (3 files × 3 reviewers) |
| 6 | Pull markdown report → `trias/results/review-<task-id>.md` |

Expected runtime: **~15–45 minutes** (9 council rounds + synthesis + skeptic).

---

## Manual steps (if you prefer)

```bash
# Sync Trias
./scripts/sync-to-gb10.sh

# Restart worker
ssh gb10 'systemctl --user restart trias || (pkill -f trias.worker; nohup trias worker >> ~/.trias/worker.log 2>&1 &)'

# Submit on GB10
ssh gb10 'cd ~/pdf-fill-jason && trias submit --wait --focus security \
  app/security.py app/auth.py app/csrf.py'

# Status / logs
ssh gb10 'trias status'
ssh gb10 'tail -f ~/.trias/worker.log'

# Pull from Mac
export TRIAS_REMOTE=gb10
trias pull TASK_ID --output results/
```

---

## What to verify in the report

1. **`file_strategy=sequential`** in the header
2. **File coverage** lists all 3 files with ✅ 3/3 reviewers each
3. **Raw reviews** grouped by file (not one mashed blob)
4. **Synthesis → FILE COVERAGE** table includes quiet files explicitly
5. Reviewers output **`CHECKLIST:`** and **`CLEAN:`** or findings per file

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Connection closed by UNKNOWN port 65535` | Start Tailscale; SOCKS proxy must listen on `localhost:1055` |
| `missing: .../app/security.py` | Run `pdf-fill-jason/deploy/sync-to-gb10.sh` |
| Worker not picking up new code | `./scripts/sync-to-gb10.sh` then `systemctl --user restart trias` |
| Task timeout | `./scripts/test-gb10-file-review.sh` with `TRIAS_TEST_TIMEOUT=7200` |
| Re-test without rsync | `./scripts/test-gb10-file-review.sh --no-sync` |

---

## Remote submit from Mac (optional)

Instead of running submit on GB10, you can push tasks from the Mac:

```bash
export TRIAS_REMOTE=gb10
cd pdf-fill-jason
trias submit --wait --focus security app/security.py app/auth.py app/csrf.py
```

Files are SCP'd to `~/.trias/uploads/` on GB10; the worker there processes them.
