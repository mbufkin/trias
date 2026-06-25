"""GB10 (and optional local) runtime for the Trias GUI — SSH, worker, submit, logs."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .report_parser import parse_report_markdown, report_list_summary

# Active review phases — used for queue warnings and live panel.
_ACTIVE_STATUSES = frozenset({"started", "reviewing", "synthesizing", "skeptic_check"})

# Rough minutes per reviewer round per file (GB10 sequential council).
_ETA_MINUTES_PER_ROUND = 4

# rsync excludes — mirror Mac project to GB10 without secrets or bulky artifacts.
_RSYNC_EXCLUDES = (
    "--exclude", ".venv",
    "--exclude", "venv",
    "--exclude", "__pycache__",
    "--exclude", "*.pyc",
    "--exclude", ".pytest_cache",
    "--exclude", ".git",
    "--exclude", ".env",
    "--exclude", "data/",
    "--exclude", "Output/",
    "--exclude", "*.db",
    "--exclude", "*.xlsx",
    "--exclude", ".DS_Store",
    "--exclude", "node_modules",
    "--exclude", ".trias",
)


@dataclass
class RuntimeConfig:
    """Where the GUI submits work and reads status."""

    mode: str = "gb10"  # gb10 | local
    gb10_host: str = "lenovo@100.85.15.59"
    pdf_dir: str = "/home/lenovo/pdf-fill-jason"
    mailbox: str = "/home/lenovo/.trias"
    project_root: str = ""
    tailscale_bin: str = field(
        default_factory=lambda: os.environ.get(
            "TAILSCALE_BIN", "/Users/michaelbufkin/homebrew/bin/tailscale"
        )
    )
    tailscaled_bin: str = field(
        default_factory=lambda: os.environ.get(
            "TAILSCALED_BIN",
            "/Users/michaelbufkin/homebrew/opt/tailscale/bin/tailscaled",
        )
    )
    tailscale_socket: str = field(
        default_factory=lambda: os.environ.get("TAILSCALE_SOCKET", "/tmp/tailscaled.sock")
    )
    tailscale_state: str = field(
        default_factory=lambda: os.environ.get(
            "TAILSCALE_STATE", os.path.expanduser("~/.tailscale/tailscaled.state")
        )
    )
    sync_before_go: bool = True

    @classmethod
    def from_env(cls, mode: str = "gb10", project: str | None = None) -> RuntimeConfig:
        sync = os.environ.get("TRIAS_GUI_SYNC", "1").lower() not in ("0", "false", "no")
        return cls(
            mode=mode,
            gb10_host=os.environ.get("TRIAS_GUI_HOST", "lenovo@100.85.15.59"),
            pdf_dir=os.environ.get("TRIAS_GUI_PDF_DIR", "/home/lenovo/pdf-fill-jason"),
            mailbox=os.environ.get("TRIAS_GUI_MAILBOX", "/home/lenovo/.trias"),
            project_root=str(Path(project or os.getcwd()).expanduser().resolve()),
            sync_before_go=sync,
        )


class GB10Runtime:
    """Remote Trias operations on GB10 via Tailscale SSH."""

    def __init__(self, config: RuntimeConfig):
        self.config = config

    def _ensure_tailscale(self) -> None:
        ts = self.config.tailscale_bin
        socket = self.config.tailscale_socket
        if self._run_local([ts, f"--socket={socket}", "status"], check=False).returncode == 0:
            return
        state_dir = os.path.dirname(self.config.tailscale_state)
        os.makedirs(state_dir, exist_ok=True)
        subprocess.run(
            ["pkill", "-f", f"tailscaled.*{os.path.basename(self.config.tailscale_state)}"],
            capture_output=True,
        )
        time.sleep(1)
        subprocess.Popen(
            [
                self.config.tailscaled_bin,
                f"--state={self.config.tailscale_state}",
                f"--socket={socket}",
                "--tun=userspace-networking",
            ],
            stdout=open("/tmp/tailscaled-user.log", "a"),
            stderr=subprocess.STDOUT,
        )
        for _ in range(20):
            time.sleep(1)
            if self._run_local([ts, f"--socket={socket}", "status"], check=False).returncode == 0:
                return
        raise RuntimeError("Tailscale did not start — check /tmp/tailscaled-user.log")

    def _run_local(self, cmd: list[str], *, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=check
        )

    def ssh(self, remote_script: str, *, timeout: int = 120) -> subprocess.CompletedProcess:
        """Run a bash script on GB10 (single quoted heredoc-safe via base64 or -c)."""
        self._ensure_tailscale()
        ts = self.config.tailscale_bin
        socket = self.config.tailscale_socket
        proxy = f"{ts} --socket={socket} nc %h %p"
        cmd = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"ProxyCommand={proxy}",
            self.config.gb10_host,
            "bash",
            "-s",
        ]
        return subprocess.run(
            cmd,
            input=remote_script,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def ssh_json(self, remote_script: str, *, timeout: int = 120) -> Any:
        result = self.ssh(remote_script, timeout=timeout)
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(err or f"SSH failed with code {result.returncode}")
        text = result.stdout.strip()
        if not text:
            return {}
        return json.loads(text)

    def ensure_mailbox(self) -> None:
        mb = shlex.quote(self.config.mailbox)
        self.ssh(
            f"mkdir -p {mb}/{{tasks,status,results,archive,uploads}}\n",
            timeout=30,
        )

    def _rsync_rsh(self) -> str:
        """SSH command for rsync over Tailscale (same transport as self.ssh)."""
        ts = self.config.tailscale_bin
        socket = self.config.tailscale_socket
        proxy = f"{ts} --socket={socket} nc %h %p"
        return f"ssh -o StrictHostKeyChecking=accept-new -o ProxyCommand={shlex.quote(proxy)}"

    def sync_project(self) -> dict[str, Any]:
        """Rsync Mac project_root → GB10 pdf_dir so Go reviews current code."""
        root = Path(self.config.project_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Project root not found: {root}")

        self._ensure_tailscale()
        remote_dir = shlex.quote(self.config.pdf_dir)
        self.ssh(f"mkdir -p {remote_dir}", timeout=30)

        dest = f"{self.config.gb10_host}:{self.config.pdf_dir}/"
        cmd = [
            "rsync",
            "-av",
            "--delete",
            *_RSYNC_EXCLUDES,
            "-e",
            self._rsync_rsh(),
            f"{root}/",
            dest,
        ]
        t0 = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
        elapsed = round(time.time() - t0, 1)
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(err[:800] or f"rsync exited {result.returncode}")

        transferred = 0
        for line in (result.stdout or "").splitlines():
            if line.strip() and not line.startswith("sending") and not line.startswith("sent "):
                transferred += 1
        return {
            "status": "synced",
            "source": str(root),
            "destination": self.config.pdf_dir,
            "elapsed_s": elapsed,
            "files_updated": transferred,
        }

    def check_llama(self) -> dict[str, Any]:
        script = """
curl -sf -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/v1/models || echo 000
"""
        result = self.ssh(script, timeout=15)
        code = (result.stdout or "").strip()
        ok = code == "200"
        return {
            "ok": ok,
            "http_code": code,
            "hint": None if ok else "Start Gemma: systemctl --user start llama-cuda@gemma4-31b",
        }

    def worker_state(self) -> dict[str, Any]:
        mb = json.dumps(self.config.mailbox)
        script = f"""
python3 <<'PY'
import json, glob, os, subprocess
mb = {mb}
lock = os.path.join(mb, "worker.lock")
pid = open(lock).read().strip() if os.path.isfile(lock) else None
proc = subprocess.run(["pgrep", "-af", "trias worker"], capture_output=True, text=True)
running = proc.returncode == 0 and bool(proc.stdout.strip())
queue = len(glob.glob(os.path.join(mb, "tasks", "*.json")))
active = None
active_statuses = {json.dumps(list(_ACTIVE_STATUSES))}
for path in sorted(glob.glob(os.path.join(mb, "status", "*.json")), key=os.path.getmtime, reverse=True):
    try:
        d = json.load(open(path))
    except Exception:
        continue
    if d.get("status") in active_statuses:
        tid = d.get("task_id", os.path.basename(path)[:-5])
        active = {{
            "task_id": tid, "status": d.get("status"),
            "current_file": d.get("current_file"),
            "file_index": d.get("file_index"), "file_total": d.get("file_total"),
            "round": d.get("round"), "total": d.get("total"),
        }}
        break
print(json.dumps({{
    "running": running, "pid": pid, "queue_depth": queue, "active_task": active,
}}))
PY
"""
        return self.ssh_json(script, timeout=30)

    def start_worker(self) -> dict[str, Any]:
        mb = shlex.quote(self.config.mailbox)
        script = f"""
export PATH="$HOME/.local/bin:$PATH"
MB={mb}
mkdir -p "$MB"
if pgrep -af '[t]rias worker' >/dev/null 2>&1; then
  PID=$(tr -d '\\n' < "$MB/worker.lock" 2>/dev/null || pgrep -f 'trias worker' | head -1)
  printf '{{"status":"already_running","pid":"%s"}}\\n' "$PID"
  exit 0
fi
nohup trias worker >> "$MB/worker.log" 2>&1 &
sleep 2
if pgrep -af '[t]rias worker' >/dev/null 2>&1; then
  PID=$(tr -d '\\n' < "$MB/worker.lock" 2>/dev/null || true)
  printf '{{"status":"started","pid":"%s"}}\\n' "$PID"
else
  echo '{{"status":"failed","error":"see worker.log"}}'
  exit 1
fi
"""
        return self.ssh_json(script, timeout=30)

    def submit_task(
        self,
        files: list[str],
        focus: str,
        review_mode: str,
        file_strategy: str,
    ) -> str:
        """Submit on GB10; returns task_id."""
        pdf = shlex.quote(self.config.pdf_dir)
        mb = shlex.quote(self.config.mailbox)
        # Escape files for remote shell
        file_args = " ".join(shlex.quote(f) for f in files)
        focus_q = shlex.quote(focus)
        task_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
        task_id_q = shlex.quote(task_id)
        files_json = json.dumps(files)
        script = f"""
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd {pdf}
TASK_ID={task_id_q}
mkdir -p {mb}/{{tasks,uploads}}/$TASK_ID
FILES={shlex.quote(files_json)}
python3 <<PY
import json, os, shutil, uuid
from datetime import datetime
from pathlib import Path

pdf = Path({json.dumps(self.config.pdf_dir)})
mb = Path({json.dumps(self.config.mailbox)})
task_id = {json.dumps(task_id)}
files = json.loads({json.dumps(files_json)})
focus = {json.dumps(focus)}
review_mode = {json.dumps(review_mode)}
file_strategy = {json.dumps(file_strategy)}

uploads = mb / "uploads" / task_id
uploads.mkdir(parents=True, exist_ok=True)
rel_files = []
for f in files:
    src = (pdf / f).resolve()
    if not str(src).startswith(str(pdf.resolve()) + os.sep) and src != pdf.resolve():
        raise SystemExit(f"path escapes project: {{f}}")
    if not src.is_file():
        raise SystemExit(f"file not found: {{f}}")
    rel = os.path.relpath(src, pdf)
    dst = uploads / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    rel_files.append(rel)

task = {{
    "task_id": task_id,
    "files": rel_files,
    "base_dir": str(uploads),
    "focus": focus,
    "review_mode": review_mode,
    "file_strategy": file_strategy,
    "submitted": datetime.now().isoformat(),
}}
(mb / "tasks" / f"{{task_id}}.json").write_text(json.dumps(task, indent=2))
print(task_id)
PY
"""
        result = self.ssh(script, timeout=180)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "").strip() or "Submit failed")
        return (result.stdout or "").strip().split("\n")[-1].strip()

    def list_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        mb = json.dumps(self.config.mailbox)
        script = f"""
python3 <<'PY'
import json, glob, os
mb = {mb}
tasks = []
for path in sorted(glob.glob(os.path.join(mb, "status", "*.json")), key=os.path.getmtime, reverse=True)[:{limit}]:
    try:
        d = json.load(open(path))
        d.setdefault("task_id", os.path.basename(path)[:-5])
        tasks.append(d)
    except Exception:
        pass
print(json.dumps(tasks))
PY
"""
        return self.ssh_json(script, timeout=30)

    def list_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        mb = json.dumps(self.config.mailbox)
        script = f"""
python3 <<'PY'
import json, glob, os
mb = {mb}
reports = []
for path in sorted(glob.glob(os.path.join(mb, "status", "*.json")), key=os.path.getmtime, reverse=True):
    try:
        st = json.load(open(path))
    except Exception:
        continue
    if st.get("status") != "completed":
        continue
    tid = st.get("task_id", os.path.basename(path)[:-5])
    entry = {{
        "task_id": tid,
        "status": "completed",
        "completed": st.get("completed"),
        "files": st.get("files") or [],
        "focus": st.get("focus") or "",
    }}
    jp = os.path.join(mb, "results", tid + ".json")
    if os.path.isfile(jp):
        try:
            parsed = json.load(open(jp))
            entry["summary"] = parsed.get("summary") or {{}}
            entry["needs_attention"] = bool(entry["summary"].get("needs_attention"))
        except Exception:
            pass
    if "summary" not in entry:
        entry["summary"] = {{"consensus_count": 0, "high": 0, "medium": 0, "needs_attention": False, "action_count": 0}}
        entry["needs_attention"] = False
    reports.append(entry)
    if len(reports) >= {limit}:
        break
print(json.dumps(reports))
PY
"""
        return self.ssh_json(script, timeout=45)

    def get_report(self, task_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", task_id):
            raise ValueError("Invalid task_id")
        mb = json.dumps(self.config.mailbox)
        pdf = json.dumps(self.config.pdf_dir)
        tid = json.dumps(task_id)
        script = f"""
python3 <<'PY'
import json, os
mb = {mb}
pdf = {pdf}
tid = {tid}
jp = os.path.join(mb, "results", tid + ".json")
mp = os.path.join(mb, "results", tid + ".md")
if not os.path.isfile(mp):
    alt = os.path.join(pdf, "review-" + tid + ".md")
    if os.path.isfile(alt):
        mp = alt
sidecar = None
md = ""
if os.path.isfile(jp):
    try:
        sidecar = json.load(open(jp))
    except Exception:
        pass
if os.path.isfile(mp):
    md = open(mp, encoding="utf-8").read()
print(json.dumps({{"sidecar": sidecar, "markdown": md}}))
PY
"""
        data = self.ssh_json(script, timeout=60)
        markdown = data.get("markdown") or ""
        if not markdown.strip():
            markdown = self.pull_report(task_id)
        if not markdown.strip():
            raise RuntimeError("Report not found")
        return build_report_payload(task_id, markdown, data.get("sidecar"))

    def read_status(self, task_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", task_id):
            raise ValueError("Invalid task_id")
        mb = shlex.quote(self.config.mailbox)
        tid = shlex.quote(task_id)
        script = f"cat {mb}/status/{tid}.json 2>/dev/null || echo '{{}}'"
        result = self.ssh(script, timeout=20)
        text = (result.stdout or "").strip()
        if not text or text == "{}":
            return {"task_id": task_id, "status": "unknown"}
        return json.loads(text)

    def tail_log(self, lines: int = 200) -> str:
        mb = shlex.quote(self.config.mailbox)
        n = max(1, min(lines, 2000))
        script = f"tail -n {n} {mb}/worker.log 2>/dev/null || echo '(no worker log yet)'"
        result = self.ssh(script, timeout=20)
        return result.stdout or ""

    def pull_report(self, task_id: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", task_id):
            raise ValueError("Invalid task_id")
        pdf = shlex.quote(self.config.pdf_dir)
        mb = shlex.quote(self.config.mailbox)
        tid = shlex.quote(task_id)
        script = f"""
export PATH="$HOME/.local/bin:$PATH"
R={pdf}/review-{tid}.md
if [[ ! -f "$R" ]]; then
  cd {pdf} && trias pull {tid} --output {pdf} >/dev/null 2>&1 || true
fi
if [[ -f "$R" ]]; then cat "$R"; elif [[ -f {mb}/results/{tid}.md ]]; then cat {mb}/results/{tid}.md
else echo ''; fi
"""
        result = self.ssh(script, timeout=60)
        return result.stdout or ""

    def runtime_snapshot(self) -> dict[str, Any]:
        llama = self.check_llama()
        worker = self.worker_state()
        return {
            "mode": "gb10",
            "gb10_host": self.config.gb10_host,
            "pdf_dir": self.config.pdf_dir,
            "llama": llama,
            "worker": worker,
        }

    @staticmethod
    def estimate_eta_minutes(file_count: int, reviewers: int = 3) -> int:
        return estimate_eta_minutes(file_count, reviewers)

    def get_queue(self) -> dict[str, Any]:
        mb = json.dumps(self.config.mailbox)
        script = f"""
python3 <<'PY'
import json, glob, os
# Inline queue builder — mirrors gui_runtime.build_queue_snapshot on GB10.
mb = {mb}
ETA_PER_ROUND = {_ETA_MINUTES_PER_ROUND}
REVIEWERS = 3
ACTIVE = {json.dumps(list(_ACTIVE_STATUSES))}

def eta_minutes(n):
    return max(1, n * REVIEWERS * ETA_PER_ROUND)

def remaining(st):
    s = st.get("status")
    if s == "synthesizing": return 3
    if s == "skeptic_check": return 2
    if s != "reviewing":
        return eta_minutes(st.get("file_total") or 1)
    fi = int(st.get("file_index") or 1)
    ft = int(st.get("file_total") or 1)
    rnd = int(st.get("round") or 1)
    tot = int(st.get("total") or 3)
    done = (max(0, fi - 1) * tot) + max(0, rnd - 1)
    rem = max(0, ft * tot - done)
    return max(1, rem * ETA_PER_ROUND + (5 if rem <= tot else 0))

pending = []
for path in sorted(glob.glob(os.path.join(mb, "tasks", "*.json")), key=os.path.getmtime):
    try:
        d = json.load(open(path))
        d.setdefault("task_id", os.path.basename(path)[:-5])
        pending.append(d)
    except Exception:
        pass

active_st = None
for path in sorted(glob.glob(os.path.join(mb, "status", "*.json")), key=os.path.getmtime, reverse=True):
    try:
        d = json.load(open(path))
    except Exception:
        continue
    if d.get("status") in ACTIVE:
        d.setdefault("task_id", os.path.basename(path)[:-5])
        active_st = d
        break

active = None
waiting = []
wait_accum = 0
if active_st:
    tid = active_st["task_id"]
    fc = int(active_st.get("file_total") or 0)
    if not fc:
        for p in pending:
            if p.get("task_id") == tid:
                fc = len(p.get("files") or [])
                break
    rem = remaining({{**active_st, "file_total": fc or 1}})
    total = eta_minutes(fc or 1)
    fi = active_st.get("file_index") or 0
    ft = active_st.get("file_total") or fc or 0
    rnd = active_st.get("round") or 0
    tot = active_st.get("total") or 3
    done = (max(0, int(fi) - 1) * int(tot)) + max(0, int(rnd))
    total_rounds = int(ft) * int(tot) if ft else 1
    pct = round(100 * done / total_rounds) if total_rounds else 0
    active = {{
        "position": 1, "task_id": tid, "status": active_st.get("status"),
        "file_count": fc, "file_index": active_st.get("file_index"),
        "file_total": active_st.get("file_total"), "round": active_st.get("round"),
        "total": active_st.get("total"), "current_file": active_st.get("current_file"),
        "eta_minutes_remaining": rem, "eta_minutes_total": total, "progress_pct": pct,
    }}
    wait_accum = rem
    pending = [p for p in pending if p.get("task_id") != tid]

pos = 2 if active else 1
for task in pending:
    files = task.get("files") or []
    fc = len(files)
    eta = eta_minutes(fc)
    waiting.append({{
        "position": pos, "task_id": task.get("task_id"), "status": "queued",
        "file_count": fc, "files_preview": files[:3], "files_extra": max(0, fc - 3),
        "focus": task.get("focus", ""), "submitted": task.get("submitted"),
        "eta_minutes": eta, "wait_minutes": wait_accum, "wait_minutes_end": wait_accum + eta,
    }})
    wait_accum += eta
    pos += 1

print(json.dumps({{"active": active, "waiting": waiting, "queue_depth": len(pending), "total_wait_minutes": wait_accum}}))
PY
"""
        return self.ssh_json(script, timeout=30)


class LocalRuntime:
    """Local mailbox runtime (Mac) — fallback when not using GB10."""

    def __init__(self, config: RuntimeConfig):
        self.config = config
        from .config import load_config
        from .cli import _submit_task

        self._load_config = load_config
        self._submit_task = _submit_task

    def ensure_mailbox(self) -> None:
        cfg = self._load_config()
        for key in ("tasks", "status", "results", "archive", "uploads"):
            Path(cfg["paths"][key]).mkdir(parents=True, exist_ok=True)

    def sync_project(self) -> dict[str, Any]:
        return {"status": "skipped", "reason": "local runtime"}

    def check_llama(self) -> dict[str, Any]:
        from .inference import check_llamacpp_health

        cfg = self._load_config()
        ok = check_llamacpp_health(cfg)
        return {"ok": ok, "hint": None if ok else "Start llama.cpp on :8080"}

    def worker_state(self) -> dict[str, Any]:
        cfg = self._load_config()
        lock_path = Path(cfg["paths"]["mailbox"]) / "worker.lock"
        pid = lock_path.read_text().strip() if lock_path.is_file() else None
        tasks_dir = Path(cfg["paths"]["tasks"])
        queue = len(list(tasks_dir.glob("*.json")))
        active = None
        for sf in sorted(Path(cfg["paths"]["status"]).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                d = json.loads(sf.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if d.get("status") in _ACTIVE_STATUSES:
                active = {"task_id": d.get("task_id", sf.stem), **d}
                break
        running = bool(pid)  # approximate
        return {"running": running, "pid": pid, "queue_depth": queue, "active_task": active}

    def start_worker(self) -> dict[str, Any]:
        cfg = self._load_config()
        lock_path = Path(cfg["paths"]["mailbox"]) / "worker.lock"
        if lock_path.is_file():
            return {"status": "already_running", "pid": lock_path.read_text().strip()}
        log_path = Path(cfg["paths"]["mailbox"]) / "worker.log"
        subprocess.Popen(
            ["trias", "worker"],
            stdout=open(log_path, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        time.sleep(2)
        if lock_path.is_file():
            return {"status": "started", "pid": lock_path.read_text().strip()}
        return {"status": "failed", "error": "worker did not acquire lock"}

    def submit_task(
        self, files: list[str], focus: str, review_mode: str, file_strategy: str
    ) -> str:
        cfg = self._load_config()
        root = Path(self.config.project_root)
        task_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
        rel_files = []
        for f in files:
            src = (root / f).resolve()
            if not str(src).startswith(str(root.resolve()) + os.sep):
                raise ValueError(f"path escapes project: {f}")
            if not src.is_file():
                raise ValueError(f"file not found: {f}")
            rel_files.append(str(src.relative_to(root)))
        task = {
            "task_id": task_id,
            "files": rel_files,
            "base_dir": str(root),
            "focus": focus,
            "review_mode": review_mode,
            "file_strategy": file_strategy,
            "submitted": datetime.now().isoformat(),
        }
        if not self._submit_task(cfg, task, task_id):
            raise RuntimeError("Failed to submit task")
        return task_id

    def list_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        cfg = self._load_config()
        tasks = []
        for sf in sorted(Path(cfg["paths"]["status"]).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            try:
                d = json.loads(sf.read_text())
                d.setdefault("task_id", sf.stem)
                tasks.append(d)
            except (json.JSONDecodeError, OSError):
                continue
        return tasks

    def read_status(self, task_id: str) -> dict[str, Any]:
        cfg = self._load_config()
        path = Path(cfg["paths"]["status"]) / f"{task_id}.json"
        if not path.is_file():
            return {"task_id": task_id, "status": "unknown"}
        return json.loads(path.read_text())

    def tail_log(self, lines: int = 200) -> str:
        cfg = self._load_config()
        path = Path(cfg["paths"]["mailbox"]) / "worker.log"
        if not path.is_file():
            return "(no worker log yet)"
        all_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(all_lines[-lines:])

    def pull_report(self, task_id: str) -> str:
        cfg = self._load_config()
        for candidate in (
            Path(cfg["paths"]["results"]) / f"{task_id}.md",
            Path(self.config.project_root) / f"review-{task_id}.md",
        ):
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")
        return ""

    def list_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        cfg = self._load_config()
        status_dir = Path(cfg["paths"]["status"])
        results_dir = Path(cfg["paths"]["results"])
        reports: list[dict[str, Any]] = []
        for sf in sorted(status_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                st = json.loads(sf.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if st.get("status") != "completed":
                continue
            tid = st.get("task_id", sf.stem)
            entry: dict[str, Any] = {
                "task_id": tid,
                "status": "completed",
                "completed": st.get("completed"),
                "files": st.get("files") or [],
                "focus": st.get("focus") or "",
            }
            json_path = results_dir / f"{tid}.json"
            if json_path.is_file():
                try:
                    parsed = json.loads(json_path.read_text())
                    entry["summary"] = parsed.get("summary") or {}
                    entry["needs_attention"] = bool(entry["summary"].get("needs_attention"))
                except (json.JSONDecodeError, OSError):
                    pass
            if "summary" not in entry:
                md_path = results_dir / f"{tid}.md"
                if md_path.is_file():
                    try:
                        parsed = parse_report_markdown(md_path.read_text(encoding="utf-8"), task_id=tid)
                        entry.update(report_list_summary(parsed))
                    except (ValueError, OSError):
                        pass
            if "summary" not in entry:
                entry["summary"] = {
                    "consensus_count": 0,
                    "high": 0,
                    "medium": 0,
                    "needs_attention": False,
                    "action_count": 0,
                }
                entry["needs_attention"] = False
            reports.append(entry)
            if len(reports) >= limit:
                break
        return reports

    def get_report(self, task_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,64}", task_id):
            raise ValueError("Invalid task_id")
        cfg = self._load_config()
        results_dir = Path(cfg["paths"]["results"])
        json_path = results_dir / f"{task_id}.json"
        sidecar: dict[str, Any] | None = None
        if json_path.is_file():
            try:
                sidecar = json.loads(json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                sidecar = None
        markdown = self.pull_report(task_id)
        if not markdown.strip():
            raise RuntimeError("Report not found")
        return build_report_payload(task_id, markdown, sidecar)

    def runtime_snapshot(self) -> dict[str, Any]:
        return {
            "mode": "local",
            "llama": self.check_llama(),
            "worker": self.worker_state(),
        }

    def get_queue(self) -> dict[str, Any]:
        cfg = self._load_config()
        return build_queue_snapshot(
            Path(cfg["paths"]["tasks"]),
            Path(cfg["paths"]["status"]),
        )

    @staticmethod
    def estimate_eta_minutes(file_count: int, reviewers: int = 3) -> int:
        return estimate_eta_minutes(file_count, reviewers)


def get_runtime(config: RuntimeConfig) -> GB10Runtime | LocalRuntime:
    if config.mode == "gb10":
        return GB10Runtime(config)
    return LocalRuntime(config)


def estimate_eta_minutes(file_count: int, reviewers: int = 3) -> int:
    return max(1, file_count * reviewers * _ETA_MINUTES_PER_ROUND)


def estimate_remaining_minutes(status: dict[str, Any]) -> int:
    """Minutes left for an in-flight review (reviewing/synthesizing)."""
    st = status.get("status")
    if st == "synthesizing":
        return 3
    if st == "skeptic_check":
        return 2
    if st != "reviewing":
        return estimate_eta_minutes(status.get("file_total") or status.get("file_count") or 1)
    fi = int(status.get("file_index") or 1)
    ft = int(status.get("file_total") or 1)
    rnd = int(status.get("round") or 1)
    tot = int(status.get("total") or 3)
    done = (max(0, fi - 1) * tot) + max(0, rnd - 1)
    total_rounds = ft * tot
    remaining_rounds = max(0, total_rounds - done)
    # synthesis + skeptic after council rounds
    extra = 5 if remaining_rounds <= tot else 0
    return max(1, remaining_rounds * _ETA_MINUTES_PER_ROUND + extra)


def _load_pending_tasks(tasks_dir: Path) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    for path in sorted(tasks_dir.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            data = json.loads(path.read_text())
            data.setdefault("task_id", path.stem)
            pending.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return pending


def _find_active_status(status_dir: Path) -> dict[str, Any] | None:
    if not status_dir.is_dir():
        return None
    for path in sorted(status_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("status") in _ACTIVE_STATUSES:
            data.setdefault("task_id", path.stem)
            return data
    return None


def build_queue_snapshot(
    tasks_dir: Path,
    status_dir: Path,
    *,
    reviewers: int = 3,
) -> dict[str, Any]:
    """Build active + waiting queue with per-item ETAs."""
    pending = _load_pending_tasks(tasks_dir)
    active_status = _find_active_status(status_dir)

    active: dict[str, Any] | None = None
    waiting: list[dict[str, Any]] = []
    wait_accum = 0

    if active_status:
        tid = active_status["task_id"]
        fc = int(active_status.get("file_total") or 0)
        if not fc:
            for p in pending:
                if p.get("task_id") == tid:
                    fc = len(p.get("files") or [])
                    break
        remaining = estimate_remaining_minutes({**active_status, "file_total": fc or 1})
        total = estimate_eta_minutes(fc or 1, reviewers)
        active = {
            "position": 1,
            "task_id": tid,
            "status": active_status.get("status"),
            "file_count": fc,
            "file_index": active_status.get("file_index"),
            "file_total": active_status.get("file_total"),
            "round": active_status.get("round"),
            "total": active_status.get("total"),
            "current_file": active_status.get("current_file"),
            "eta_minutes_remaining": remaining,
            "eta_minutes_total": total,
            "progress_pct": enrich_live_status(active_status, fc).get("progress_pct", 0),
        }
        wait_accum = remaining
        pending = [p for p in pending if p.get("task_id") != tid]

    pos = 2 if active else 1
    for task in pending:
        files = task.get("files") or []
        fc = len(files)
        eta = estimate_eta_minutes(fc, reviewers)
        waiting.append(
            {
                "position": pos,
                "task_id": task.get("task_id"),
                "status": "queued",
                "file_count": fc,
                "files_preview": files[:3],
                "files_extra": max(0, fc - 3),
                "focus": task.get("focus", ""),
                "submitted": task.get("submitted"),
                "eta_minutes": eta,
                "wait_minutes": wait_accum,
                "wait_minutes_end": wait_accum + eta,
            }
        )
        wait_accum += eta
        pos += 1

    return {
        "active": active,
        "waiting": waiting,
        "queue_depth": len(pending),
        "total_wait_minutes": wait_accum,
    }


def build_report_payload(
    task_id: str,
    markdown: str,
    sidecar: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge sidecar JSON with markdown; parse on demand for legacy reports."""
    if sidecar and sidecar.get("task_id"):
        parsed = dict(sidecar)
    else:
        parsed = parse_report_markdown(markdown, task_id=task_id)
    parsed["markdown"] = markdown
    return parsed


def enrich_live_status(status: dict[str, Any], file_count: int | None = None) -> dict[str, Any]:
    """Add elapsed hint, progress %, and ETA for the live panel."""
    out = dict(status)
    updated = status.get("updated") or status.get("submitted")
    if updated:
        try:
            from datetime import timezone

            ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            elapsed_s = (datetime.now(timezone.utc) - ts).total_seconds()
            out["elapsed_s"] = round(max(0, elapsed_s))
        except (ValueError, TypeError):
            pass
    fi = int(status.get("file_index") or 0)
    ft = int(status.get("file_total") or file_count or 0)
    rnd = int(status.get("round") or 0)
    tot = int(status.get("total") or 3)
    if ft and status.get("status") == "reviewing":
        done_rounds = (max(0, fi - 1) * tot) + max(0, rnd)
        total_rounds = ft * tot
        out["progress_pct"] = round(100 * done_rounds / total_rounds) if total_rounds else 0
    fc = file_count or ft or int(status.get("file_count") or 0)
    if fc:
        out["eta_minutes"] = estimate_eta_minutes(fc)
        rem = estimate_remaining_minutes({**status, "file_total": ft or fc})
        out["eta_minutes_remaining"] = rem
    return out
