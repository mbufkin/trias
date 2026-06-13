#!/usr/bin/env python3
"""
Review Council CLI — submit code for multi-model review, check status, pull results.

Usage:
  review-council submit --wait file1.py file2.js
  review-council submit --focus "security, performance" *.py
  review-council status
  review-council pull TASK_ID
  review-council worker              # start the daemon
"""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from .config import load_config

# Remote transport: use SSH if TRIAS_REMOTE is set, otherwise local file ops
REMOTE_HOST = os.environ.get("TRIAS_REMOTE", "")


def _is_remote() -> bool:
    return bool(REMOTE_HOST)


def _run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _submit_task(config: dict, task: dict, task_id: str) -> bool:
    """Submit a task to the mailbox, local or remote."""
    tasks_dir = config["paths"]["tasks"]
    uploads_dir = Path(config["paths"]["uploads"]) / task_id
    files = task.get("files", [])
    base_dir = task.get("base_dir", os.getcwd())

    remote_prefix = f"{REMOTE_HOST}:" if _is_remote() else ""

    # Create uploads directory
    if _is_remote():
        _run(["ssh", REMOTE_HOST, "mkdir", "-p", str(uploads_dir)])
    else:
        uploads_dir.mkdir(parents=True, exist_ok=True)

    for f in files:
        src = os.path.join(base_dir, f)
        dst_name = os.path.basename(f)  # strip directory, keep filename
        if _is_remote():
            result = _run(["scp", src, f"{remote_prefix}{uploads_dir}/{dst_name}"])
        else:
            import shutil
            shutil.copy2(src, uploads_dir / dst_name)
            result = subprocess.CompletedProcess([], 0, "", "")
        if result.returncode != 0:
            print(f"ERROR: Failed to upload {f}")
            print(f"  scp stderr: {result.stderr[:300]}")
            return False

    # Update task with remote base_dir
    task["base_dir"] = str(uploads_dir)

    # Write and place task
    local_task = Path(f"/tmp/review-task-{task_id}.json")
    local_task.write_text(json.dumps(task, indent=2))

    if _is_remote():
        result = _run(["scp", str(local_task),
                       f"{remote_prefix}{tasks_dir}/{task_id}.json"])
    else:
        import shutil
        shutil.copy2(str(local_task), Path(tasks_dir) / f"{task_id}.json")
        result = subprocess.CompletedProcess([], 0, "", "")

    local_task.unlink(missing_ok=True)
    return result.returncode == 0


def _read_remote(path: str) -> str:
    """Read a file, remote if REMOTE_HOST is set. Uses list-based args to prevent injection."""
    if _is_remote():
        result = _run(["ssh", REMOTE_HOST, "cat", "--", path])
        return result.stdout if result.returncode == 0 else ""
    else:
        try:
            return Path(path).read_text()
        except FileNotFoundError:
            return ""


def cmd_status(config: dict):
    """Check worker status."""
    status_dir = config["paths"]["status"]

    if _is_remote():
        result = _run(["ssh", REMOTE_HOST, "sh", "-c",
                       f"ls {status_dir}/ 2>/dev/null || true"])
        files = [f for f in result.stdout.strip().split("\n") if f.endswith('.json')]
    else:
        files = [f.name for f in Path(status_dir).glob("*.json")]

    if not files:
        print("No tasks found.")
        return

    print(f"{'TASK ID':<40} {'STATUS':<15} {'UPDATED'}")
    print("-" * 75)
    for sf in sorted(files):
        data_str = _read_remote(f"{status_dir}/{sf}")
        try:
            data = json.loads(data_str)
            task_id = data.get("task_id", sf.replace(".json", ""))
            status = data.get("status", "unknown")
            updated = data.get("updated", "")[:19].replace("T", " ")
            extra = ""
            if status == "reviewing":
                extra = f" | R{data.get('round','?')}/{data.get('total','?')} — {data.get('model','?')}"
            elif status == "completed":
                extra = f" | {data.get('succeeded','?')}/{data.get('succeeded',0)+data.get('failed',0)} ok, {data.get('total_time_s','?')}s"
            print(f"{task_id:<40} {status:<15} {updated}{extra}")
        except json.JSONDecodeError:
            print(f"{sf:<40} [invalid json]")


def cmd_pull(config: dict, task_id: str, output_dir: str = "."):
    """Pull review results."""
    results_dir = config["paths"]["results"]
    remote_path = f"{results_dir}/{task_id}.md"
    local_path = os.path.join(output_dir, f"review-{task_id}.md")

    if _is_remote():
        # Try to scp directly — if file doesn't exist, scp will fail
        result = _run(["scp", f"{REMOTE_HOST}:{remote_path}", local_path], timeout=15)
        if result.returncode != 0:
            print(f"Results not found for {task_id} (or scp failed).")
            return
    else:
        src = Path(remote_path)
        if not src.exists():
            print(f"Results not found for {task_id}.")
            return
        import shutil
        shutil.copy2(str(src), local_path)

    print(f"Results: {local_path}")
    # Print preview
    content = Path(local_path).read_text()
    lines = content.split("\n")
    for line in lines[:60]:
        print(line)


def cmd_submit(config: dict, files: list[str], focus: str, wait: bool = False):
    """Submit a review task."""
    task_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]

    for f in files:
        if not os.path.exists(f):
            print(f"ERROR: File not found: {f}")
            sys.exit(1)

    task = {
        "task_id": task_id,
        "files": [os.path.basename(f) for f in files],
        "base_dir": os.getcwd(),
        "focus": focus,
        "submitted": datetime.now().isoformat(),
    }

    if not _submit_task(config, task, task_id):
        print("ERROR: Failed to submit task.")
        sys.exit(1)

    print(f"Submitted: {task_id}")
    print(f"Files: {', '.join(files)}")
    print(f"Focus: {focus}")

    if wait:
        cmd_wait(config, task_id)
    else:
        print(f"\nStatus: review-council status")
        print(f"Results: review-council pull {task_id}")


def cmd_wait(config: dict, task_id: str):
    """Wait for task completion."""
    MAX_WAIT = 900
    POLL_INTERVAL = 30
    status_dir = config["paths"]["status"]
    status_path = f"{status_dir}/{task_id}.json"

    print(f"Waiting for {task_id}...", end="", flush=True)
    elapsed = 0
    last_status = ""

    while elapsed < MAX_WAIT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        data_str = _read_remote(status_path)
        if not data_str.strip():
            print(".", end="", flush=True)
            continue

        try:
            data = json.loads(data_str)
            status = data.get("status", "")

            if status == "reviewing":
                progress = f"R{data.get('round','?')}/{data.get('total','?')}"
                if progress != last_status:
                    print(f"\n  [{progress}] {data.get('model', '')}...", end="", flush=True)
                    last_status = progress
                continue
            elif status == "synthesizing":
                if last_status != "synth":
                    print(f"\n  [Synthesizing]...", end="", flush=True)
                    last_status = "synth"
                continue

            if status == "failed":
                print(f"\n❌ Failed: {data.get('error', 'unknown')}")
                return

            if status == "completed" or data.get("completed"):
                print(f"\n✅ Done in {data.get('total_time_s', '?')}s")
                cmd_pull(config, task_id)
                return

        except json.JSONDecodeError:
            pass

        print(".", end="", flush=True)

    print(f"\n⏰ Timed out after {MAX_WAIT}s.")


def main():
    parser = argparse.ArgumentParser(
        description="Review Council — multi-model code review, local-first")
    sub = parser.add_subparsers(dest="command")

    # submit
    p_submit = sub.add_parser("submit", help="Submit files for review")
    p_submit.add_argument("files", nargs="+", help="Files to review")
    p_submit.add_argument("--focus", help="Review focus areas")
    p_submit.add_argument("--wait", action="store_true", help="Wait for results")

    # status
    sub.add_parser("status", help="Check task status")

    # pull
    p_pull = sub.add_parser("pull", help="Pull results")
    p_pull.add_argument("task_id", help="Task ID")
    p_pull.add_argument("--output", default=".", help="Output directory")

    # worker
    p_worker = sub.add_parser("worker", help="Start the review daemon")
    p_worker.add_argument("--config", help="Config file path")

    # config
    p_config = sub.add_parser("init", help="Write default config")
    p_config.add_argument("--output", default="config.yaml", help="Output path")

    args = parser.parse_args()

    if args.command == "init":
        from .config import _DEFAULT_CONFIG
        import yaml
        with open(args.output, "w") as f:
            yaml.dump(_DEFAULT_CONFIG, f, default_flow_style=False, sort_keys=False)
        print(f"Config written: {args.output}")
        return

    config = load_config()

    if args.command == "worker":
        from .worker import run_worker
        run_worker(getattr(args, "config", None))
    elif args.command == "status":
        cmd_status(config)
    elif args.command == "pull":
        cmd_pull(config, args.task_id, args.output)
    elif args.command == "submit":
        focus = args.focus or config["review"]["focus"]
        cmd_submit(config, args.files, focus, args.wait)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
