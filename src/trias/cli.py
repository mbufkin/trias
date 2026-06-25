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
        dst_name = f  # preserve relative path for subdirectory support
        dst_dir = os.path.dirname(str(uploads_dir / dst_name))
        if _is_remote():
            _run(["ssh", REMOTE_HOST, "mkdir", "-p", dst_dir])
        else:
            Path(dst_dir).mkdir(parents=True, exist_ok=True)
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

    tasks_path = Path(tasks_dir)
    tasks_path.mkdir(parents=True, exist_ok=True)

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
        result = _run(["ssh", REMOTE_HOST, "ls", f"{status_dir}/"],
                      timeout=15)
        # ls exits 2 if dir doesn't exist; treat as empty listing
        if result.returncode != 0 and result.returncode != 2:
            files = []
        else:
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
                if data.get("current_file"):
                    extra += f" | {data.get('file_index','?')}/{data.get('file_total','?')} {data.get('current_file')}"
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


def cmd_submit(
    config: dict,
    files: list[str],
    focus: str,
    wait: bool = False,
    timeout: int = 1200,
    review_mode: str | None = None,
    file_strategy: str | None = None,
):
    """Submit a review task."""
    task_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]

    for f in files:
        if not os.path.exists(f):
            print(f"ERROR: File not found: {f}")
            sys.exit(1)

    rev = config.get("review", {})
    task = {
        "task_id": task_id,
        "files": [os.path.relpath(f, os.getcwd()) for f in files],
        "base_dir": os.getcwd(),
        "focus": focus,
        "review_mode": review_mode or rev.get("mode", "council"),
        "file_strategy": file_strategy or rev.get("file_strategy", "sequential"),
        "submitted": datetime.now().isoformat(),
    }

    if not _submit_task(config, task, task_id):
        print("ERROR: Failed to submit task.")
        sys.exit(1)

    print(f"Submitted: {task_id}")
    print(f"Files ({len(files)}): {', '.join(files)}")
    print(f"Focus: {focus}")
    strategy = config.get("review", {}).get("file_strategy", "sequential")
    if len(files) > 1 and strategy == "sequential":
        print(
            f"Review: sequential — each file gets the full council "
            f"({len(config.get('council', []))} reviewers × {len(files)} files). "
            f"See docs/FILE-BY-FILE-REVIEW.md"
        )

    if wait:
        cmd_wait(config, task_id, timeout)
    else:
        print(f"\nStatus: review-council status")
        print(f"Results: review-council pull {task_id}")


def cmd_wait(config: dict, task_id: str, max_wait: int = 1200):
    """Wait for task completion."""
    POLL_INTERVAL = 15
    status_dir = config["paths"]["status"]
    status_path = f"{status_dir}/{task_id}.json"

    print(f"Waiting for {task_id}...", end="", flush=True)
    elapsed = 0
    last_status = ""

    while elapsed < max_wait:
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
                if data.get("current_file"):
                    progress += f" | {data.get('file_index','?')}/{data.get('file_total','?')} {data.get('current_file')}"
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

    print(f"\n⏰ Timed out after {max_wait}s.")


def _default_scan_report(project: Path, mode: str) -> Path:
    from datetime import datetime, timezone

    repo_root = Path(__file__).resolve().parents[2]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return repo_root / "results" / f"{project.name}-scan-{mode}-{stamp}.md"


def _resolve_smoke_arg(project: Path, smoke: Path | None) -> Path | None:
    if smoke is None:
        return None
    return smoke if smoke.is_absolute() else project / smoke


def _add_scan_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", type=Path, required=True, help="Project root")
    parser.add_argument("--report", type=Path, default=None, help="Markdown report path")


def cmd_scan(args) -> int:
    """Run one passive scan mode (static, deps, deploy, or explicit all)."""
    from .scan import run_all, run_deps, run_deploy, run_static

    project: Path = Path(args.project)
    report = args.report or _default_scan_report(project, args.scan_mode)

    if args.scan_mode == "static":
        return run_static(
            project,
            bandit_paths=args.bandit,
            report_path=report,
        )
    if args.scan_mode == "deps":
        return run_deps(
            project,
            requirements_name=args.requirements,
            report_path=report,
        )
    if args.scan_mode == "deploy":
        return run_deploy(
            project,
            smoke_script=_resolve_smoke_arg(project, args.smoke),
            ssh=args.ssh if args.ssh else None,
            smoke_extra=args.smoke_args,
            report_path=report,
        )
    if args.scan_mode == "all":
        return run_all(
            project,
            bandit_paths=args.bandit,
            requirements_name=args.requirements,
            smoke_script=_resolve_smoke_arg(project, args.smoke),
            ssh=args.ssh if args.ssh else None,
            smoke_extra=args.smoke_args,
            report_path=report,
        )
    raise SystemExit(f"unknown scan mode: {args.scan_mode}")


def main():
    parser = argparse.ArgumentParser(
        description="Trias — multi-model code review + passive project scans")
    sub = parser.add_subparsers(dest="command")

    # submit
    p_submit = sub.add_parser("submit", help="Submit files for LLM review")
    p_submit.add_argument("files", nargs="+", help="Files to review")
    p_submit.add_argument("--focus", help="Review focus areas")
    p_submit.add_argument("--review-mode", choices=["council", "focused"], help="Override review.mode")
    p_submit.add_argument("--file-strategy", choices=["sequential", "batch"], help="Override review.file_strategy")
    p_submit.add_argument("--wait", action="store_true", help="Wait for results")
    p_submit.add_argument("--timeout", type=int, default=1200, help="Max seconds to wait (default: 1200)")

    # status
    sub.add_parser("status", help="Check task status")

    # pull
    p_pull = sub.add_parser("pull", help="Pull results")
    p_pull.add_argument("task_id", help="Task ID")
    p_pull.add_argument("--output", default=".", help="Output directory")

    # worker
    p_worker = sub.add_parser("worker", help="Start the review daemon")
    p_worker.add_argument("--config", help="Config file path")

    # gui — local web UI for file/mode selection
    p_gui = sub.add_parser("gui", help="Start local web GUI (file picker + mode selection)")
    p_gui.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    p_gui.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    p_gui.add_argument(
        "--project",
        type=Path,
        default=None,
        help="Default project root for file listing (default: cwd)",
    )
    p_gui.add_argument(
        "--runtime",
        choices=["gb10", "local"],
        default=os.environ.get("TRIAS_GUI_RUNTIME", "gb10"),
        help="Where to run reviews (default: gb10)",
    )
    p_gui.add_argument(
        "--gb10-host",
        default=os.environ.get("TRIAS_GUI_HOST", "lenovo@100.85.15.59"),
        help="GB10 SSH host (default: lenovo@100.85.15.59)",
    )
    p_gui.add_argument(
        "--no-sync",
        action="store_true",
        help="Do not rsync project to GB10 before Go (default: sync enabled)",
    )

    # config
    p_config = sub.add_parser("init", help="Write default config")
    p_config.add_argument("--output", default="config.yaml", help="Output path")

    # scan — one passive mode per invocation. Active HTTP probes: Peira (separate).
    # See docs/SECURITY-LANES.md.
    p_scan = sub.add_parser("scan", help="Passive scan — one mode per run")
    scan_sub = p_scan.add_subparsers(dest="scan_mode", required=True)

    p_static = scan_sub.add_parser("static", help="Bandit — source pattern scan")
    _add_scan_common_args(p_static)
    p_static.add_argument(
        "--bandit",
        nargs="+",
        default=None,
        help="Paths under --project (default: .trias.yaml or app + scripts)",
    )

    p_deps = scan_sub.add_parser("deps", help="pip-audit — dependency vulnerabilities")
    _add_scan_common_args(p_deps)
    p_deps.add_argument(
        "--requirements",
        default=None,
        help="Requirements file under --project (default: .trias.yaml or requirements.txt)",
    )

    p_deploy = scan_sub.add_parser("deploy", help="Project smoke script (often needs live/SSH)")
    _add_scan_common_args(p_deploy)
    p_deploy.add_argument(
        "--smoke",
        type=Path,
        default=None,
        help="Smoke script (default: scan.deploy.smoke in .trias.yaml)",
    )
    p_deploy.add_argument(
        "--ssh",
        action="store_true",
        help="Pass --ssh to smoke script (overrides .trias.yaml smoke_ssh)",
    )
    p_deploy.add_argument(
        "--smoke-arg",
        action="append",
        default=[],
        dest="smoke_args",
        metavar="ARG",
        help="Extra args for smoke script",
    )

    p_all = scan_sub.add_parser(
        "all",
        help="Run static + deps + deploy (explicit CI/nightly convenience only)",
    )
    _add_scan_common_args(p_all)
    p_all.add_argument("--bandit", nargs="+", default=None)
    p_all.add_argument("--requirements", default=None)
    p_all.add_argument("--smoke", type=Path, default=None)
    p_all.add_argument("--ssh", action="store_true")
    p_all.add_argument(
        "--smoke-arg",
        action="append",
        default=[],
        dest="smoke_args",
        metavar="ARG",
    )

    args = parser.parse_args()

    if args.command == "init":
        from .config import _DEFAULT_CONFIG
        import yaml
        with open(args.output, "w") as f:
            yaml.dump(_DEFAULT_CONFIG, f, default_flow_style=False, sort_keys=False)
        print(f"Config written: {args.output}")
        return

    if args.command == "scan":
        sys.exit(cmd_scan(args))

    config = load_config()

    if args.command == "worker":
        from .worker import run_worker
        run_worker(getattr(args, "config", None))
    elif args.command == "gui":
        from .gui_server import run_gui
        run_gui(
            host=args.host,
            port=args.port,
            project=str(args.project) if args.project else None,
            runtime=args.runtime,
            gb10_host=args.gb10_host,
            sync_before_go=not args.no_sync,
        )
    elif args.command == "status":
        cmd_status(config)
    elif args.command == "pull":
        cmd_pull(config, args.task_id, args.output)
    elif args.command == "submit":
        focus = args.focus or config["review"]["focus"]
        cmd_submit(
            config,
            args.files,
            focus,
            args.wait,
            args.timeout,
            review_mode=getattr(args, "review_mode", None),
            file_strategy=getattr(args, "file_strategy", None),
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
