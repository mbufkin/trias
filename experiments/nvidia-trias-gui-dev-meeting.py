#!/usr/bin/env python3
"""NVIDIA NIM dev-meeting: Trias GUI + GB10 research stack — what's missing?"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CHOROS_ENV = Path.home() / "Desktop" / "choros" / ".env"
TRIAS_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = Path(__file__).resolve().parent / "results"

MODEL_CANDIDATES = [
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "nvidia/nemotron-4-340b-instruct",
    "meta/llama-3.3-70b-instruct",
]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def chat(base_url: str, api_key: str, model: str, system: str, user: str, timeout_s: int = 300) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
        "max_tokens": 4500,
        "stream": False,
    }
    url = base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def read_snip(path: Path, limit: int = 8000) -> str:
    if not path.is_file():
        return f"(missing: {path})"
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def main() -> None:
    load_dotenv(CHOROS_ENV)
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("NVIDIA_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    if not api_key:
        raise SystemExit("No LLM_API_KEY — set in ~/Desktop/choros/.env")

    context = f"""
## Who this is for
Michael — solo developer / DISD CTE. Builds internal tools with strong privacy (FERPA). Uses AI heavily but hates slop and wants local-first where student data is involved.

## Hardware & infra
- **GB10** — Lenovo ThinkStation PGX @ Tailscale 100.85.15.59, user lenovo. Gemma 4 31B via llama.cpp :8080. Trias worker runs here.
- **Work Pi** — raspberrypi, Travel PDF app deployed (OAuth, allowlist, PDF wizard). Cloudflare tunnel (often flaky).
- **Mac** — dev machine, Trias GUI runs locally, submits to GB10 over SSH + userspace Tailscale.

## Trias (local-first code review)
- 3 LLM reviewers (same Gemma, different prompts) × sequential file-by-file review + synthesis + skeptic gate.
- Passive lanes: Bandit, pip-audit, deploy smoke (separate `trias scan` modes).
- Mailbox: ~/.trias/{{tasks,status,results,uploads,worker.log}}
- Completed: full security review of Travel PDF (~24 modules, 4 batches, ~2.5h on GB10).

## Trias GUI (just built — GB10-first)
- `trias gui --runtime gb10 --project pdf-fill-jason` → http://127.0.0.1:8765
- **Go button**: check llama → start worker (graceful if running) → submit to GB10 mailbox
- File picker: all-files toggle, paste paths, multi-hour runs OK
- Live panel: polls status JSON + worker.log tail every 2-3s
- **Gap user noticed**: queue shows depth but NOT per-item ETA or what's in each queued task
- Submit validates files on Mac project root but copies from GB10 ~/pdf-fill-jason (must rsync first)
- No Gemma auto-start from GUI; no cancel/pause; no SSE; stdlib HTTP server only

## gui_runtime.py API surface
GET /api/runtime, /api/tasks, /api/tasks/{{id}}/live, /api/log, /api/files?all=1
POST /api/go, /api/files/add

ETA formula today: files × 3 reviewers × 4 min (rough, no queue position math)

## Travel PDF (main app under review)
Flask wizard, Google OAuth, job queue for PDF generation, roster DB, GSA rates. P0 deploy fixes done on Pi. P1 code fixes pending (diagnostics crash, destination_id validation, job owner gap).

## Related tools NOT yet integrated into GUI
- Peira (active URL probing) — separate, run when tunnel stable
- trias scan static/deps/deploy — CLI only
- GB10 UI design council — separate script, 3 passes done
- decode side / DataBox — strictly off limits for agents (FERPA)

## Current live state (approx)
Worker PID 313033 on GB10, llama OK, active review on 3-file job (errors/security/csrf), 2 tasks queued from GUI tests.

## gui_server excerpt
{read_snip(TRIAS_ROOT / "src/trias/gui_server.py", 4000)}

## README GUI section
{read_snip(TRIAS_ROOT / "README.md", 2500)}
"""

    system = """You are a principal engineer and product strategist chairing a development meeting.
Your job: review what exists, identify gaps, prioritize ruthlessly for a solo builder running multi-hour local LLM jobs.
Be concrete — name features, APIs, UX patterns, ops runbooks. No generic agile fluff.
Assume FERPA constraints: student data stays local; cloud APIs OK for meta/tooling discussions but NOT for student roster content."""

    user = f"""{context}

---

Run a **development meeting** with these sections:

1. **What we got right** (3-5 bullets) — validate the GB10-first GUI architecture
2. **Queue & observability gaps** — user wants per-queue-item ETA, status, file counts, position; what to build?
3. **Go button & worker lifecycle** — what's missing for reliable multi-hour runs (cancel, resume, systemd, sync-before-submit)?
4. **File selection UX** — any file, 100+ file runs; what safeguards and UX do we need?
5. **Integration roadmap** — should scan lanes, Peira, design council, security report feed into one dashboard?
6. **What Michael is probably missing** — blind spots (ops, testing, cost of Gemma uptime, stale GB10 code, notification when done, etc.)
7. **Prioritized backlog** — exactly 10 items, P0/P1/P2, with effort (S/M/L)

End with **3 questions you would ask Michael** to refine the roadmap."""

    model_used = None
    answer = None
    last_err = None
    for model in MODEL_CANDIDATES:
        print(f"Trying {model}...")
        t0 = time.time()
        try:
            answer = chat(base_url, api_key, model, system, user)
            model_used = model
            print(f"  OK in {time.time() - t0:.0f}s, {len(answer)} chars")
            break
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            last_err = f"{model}: HTTP {e.code} — {body}"
            print(f"  FAIL: {last_err[:150]}")
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            last_err = f"{model}: {e}"
            print(f"  FAIL: {last_err}")

    if not answer:
        raise SystemExit(f"All models failed. Last: {last_err}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = model_used.replace("/", "-")
    out = OUT_DIR / f"nvidia-trias-gui-dev-meeting-{slug}-{stamp}.md"
    out.write_text(
        f"# Trias GUI dev meeting — {stamp} UTC\n\n"
        f"- Model: `{model_used}`\n"
        f"- API: `{base_url}`\n\n"
        f"{answer}\n",
        encoding="utf-8",
    )
    print(f"\nSaved: {out}\n")
    print(answer)


if __name__ == "__main__":
    main()
