"""Local web GUI for Trias — GB10-first control panel with Go, live progress, and logs."""

from __future__ import annotations

import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import load_config
from .gui_runtime import (
    RuntimeConfig,
    enrich_live_status,
    get_runtime,
)

_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "results",
    "uploads",
}

_DEFAULT_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".yaml", ".yml", ".sh", ".md"}

FOCUS_PRESETS = [
    "security",
    "correctness",
    "performance",
    "security, correctness",
    "security, deep vs shallow modules, seams & interfaces",
]

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _safe_project_path(root: Path, rel: str = "") -> Path | None:
    try:
        base = root.expanduser().resolve()
        target = (base / rel).resolve()
    except (OSError, ValueError):
        return None
    if base == target or str(target).startswith(str(base) + os.sep):
        return target
    return None


def _list_files(root: Path, *, all_files: bool = False) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    base = root.expanduser().resolve()
    if not base.is_dir():
        return files

    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".trias")
        )
        rel_dir = Path(dirpath).relative_to(base)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if not all_files and path.suffix.lower() not in _DEFAULT_EXTENSIONS:
                continue
            rel = str(rel_dir / name).replace("\\", "/")
            if rel == ".":
                rel = name
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            files.append({"path": rel, "name": name, "size": size})
    return files


class TriasGuiHandler(BaseHTTPRequestHandler):
    config: dict = {}
    runtime_config: RuntimeConfig = RuntimeConfig()
    runtime: Any = None
    sync_before_go: bool = True

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            return self._serve_static("index.html", "text/html; charset=utf-8")
        if path.startswith("/static/"):
            return self._serve_static(path.removeprefix("/static/"))

        if path == "/api/config":
            rev = self.config.get("review", {})
            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "default_project": self.runtime_config.project_root,
                    "runtime": self.runtime_config.mode,
                    "gb10_host": self.runtime_config.gb10_host,
                    "pdf_dir": self.runtime_config.pdf_dir,
                    "review_mode": rev.get("mode", "council"),
                    "file_strategy": rev.get("file_strategy", "sequential"),
                    "focus": rev.get("focus", ""),
                    "focus_presets": FOCUS_PRESETS,
                    "review_modes": [
                        {"id": "council", "label": "Council (3 reviewers × N files)"},
                        {"id": "focused", "label": "Focused (security / architecture / correctness)"},
                    ],
                    "file_strategies": [
                        {"id": "sequential", "label": "Sequential — one file at a time (recommended)"},
                        {"id": "batch", "label": "Batch — all files in one prompt (small sets only)"},
                    ],
                    "sync_before_go": self.sync_before_go and self.runtime_config.mode == "gb10",
                    "extensions": sorted(_DEFAULT_EXTENSIONS),
                },
            )

        if path == "/api/runtime":
            try:
                snap = self.runtime.runtime_snapshot()
                return _json_response(self, HTTPStatus.OK, snap)
            except Exception as exc:
                return _json_response(
                    self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)}
                )

        if path == "/api/files":
            root_str = qs.get("root", [self.runtime_config.project_root])[0]
            all_files = qs.get("all", ["0"])[0] in ("1", "true", "yes")
            root = Path(root_str).expanduser()
            if not root.is_dir():
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": f"Not a directory: {root_str}"})
            files = _list_files(root, all_files=all_files)
            return _json_response(
                self, HTTPStatus.OK, {"root": str(root.resolve()), "files": files, "all_files": all_files},
            )

        if path == "/api/log":
            lines = int(qs.get("lines", ["200"])[0])
            try:
                text = self.runtime.tail_log(lines)
                return _json_response(self, HTTPStatus.OK, {"log": text})
            except Exception as exc:
                return _json_response(self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})

        if path == "/api/tasks":
            try:
                tasks = self.runtime.list_tasks()
                return _json_response(self, HTTPStatus.OK, {"tasks": tasks})
            except Exception as exc:
                return _json_response(self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})

        if path == "/api/queue":
            try:
                snap = self.runtime.get_queue()
                return _json_response(self, HTTPStatus.OK, snap)
            except Exception as exc:
                return _json_response(self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})

        if path == "/api/reports":
            limit = int(qs.get("limit", ["20"])[0])
            try:
                reports = self.runtime.list_reports(limit=limit)
                return _json_response(self, HTTPStatus.OK, {"reports": reports})
            except Exception as exc:
                return _json_response(self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})

        if path.startswith("/api/reports/"):
            task_id = path.removeprefix("/api/reports/")
            try:
                report = self.runtime.get_report(task_id)
                return _json_response(self, HTTPStatus.OK, report)
            except ValueError as exc:
                return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": str(exc)})

        if path.startswith("/api/tasks/") and path.endswith("/live"):
            task_id = path.removeprefix("/api/tasks/").removesuffix("/live")
            try:
                status = self.runtime.read_status(task_id)
                enriched = enrich_live_status(status)
                return _json_response(self, HTTPStatus.OK, enriched)
            except Exception as exc:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": str(exc)})

        if path.startswith("/api/tasks/"):
            task_id = path.removeprefix("/api/tasks/")
            try:
                data = self.runtime.read_status(task_id)
                return _json_response(self, HTTPStatus.OK, data)
            except Exception as exc:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": str(exc)})

        if path.startswith("/api/results/"):
            task_id = path.removeprefix("/api/results/")
            try:
                md = self.runtime.pull_report(task_id)
                if not md.strip():
                    return _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Report not ready"})
                return _json_response(self, HTTPStatus.OK, {"task_id": task_id, "markdown": md})
            except Exception as exc:
                return _json_response(self, HTTPStatus.NOT_FOUND, {"error": str(exc)})

        _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON body"})

        if self.path == "/api/runtime/worker":
            try:
                result = self.runtime.start_worker()
                return _json_response(self, HTTPStatus.OK, result)
            except Exception as exc:
                return _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        if self.path == "/api/go":
            return self._handle_go(body)

        if self.path == "/api/submit":
            return self._handle_go(body)

        if self.path == "/api/files/add":
            root = Path(body.get("project_root", self.runtime_config.project_root)).expanduser()
            paths = body.get("paths") or []
            valid: list[str] = []
            invalid: list[str] = []
            for p in paths:
                p = str(p).strip()
                if not p:
                    continue
                target = _safe_project_path(root, p)
                if target and target.is_file():
                    valid.append(str(target.relative_to(root.resolve())).replace("\\", "/"))
                else:
                    invalid.append(p)
            return _json_response(
                self,
                HTTPStatus.OK,
                {"valid": valid, "invalid": invalid},
            )

        _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def _handle_go(self, body: dict[str, Any]) -> None:
        try:
            files = body.get("files") or []
            if not files:
                raise ValueError("Select at least one file")

            focus = (body.get("focus") or self.config["review"]["focus"]).strip()
            review_mode = body.get("review_mode") or self.config["review"].get("mode", "council")
            file_strategy = body.get("file_strategy") or self.config["review"].get("file_strategy", "sequential")
            if review_mode not in ("council", "focused"):
                raise ValueError("review_mode must be council or focused")
            if file_strategy not in ("sequential", "batch"):
                raise ValueError("file_strategy must be sequential or batch")

            # Validate paths exist under project root (Mac browse path).
            root = Path(self.runtime_config.project_root)
            clean_files: list[str] = []
            for f in files:
                t = _safe_project_path(root, f)
                if not t or not t.is_file():
                    raise ValueError(f"File not found under project: {f}")
                clean_files.append(str(t.relative_to(root.resolve())).replace("\\", "/"))

            self.runtime.ensure_mailbox()

            sync_result: dict[str, Any] | None = None
            do_sync = body.get("sync", self.sync_before_go)
            if self.runtime_config.mode == "gb10" and do_sync:
                sync_result = self.runtime.sync_project()

            llama = self.runtime.check_llama()
            if not llama.get("ok"):
                return _json_response(
                    self,
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "error": llama.get("hint") or "llama.cpp is not reachable on GB10",
                        "llama": llama,
                    },
                )

            worker_result = self.runtime.start_worker()
            worker_snap = self.runtime.worker_state()
            active = worker_snap.get("active_task")
            queued_behind = None
            if active and active.get("task_id"):
                queued_behind = active["task_id"]

            task_id = self.runtime.submit_task(
                clean_files, focus, review_mode, file_strategy
            )
            eta = self.runtime.estimate_eta_minutes(len(clean_files))

            return _json_response(
                self,
                HTTPStatus.OK,
                {
                    "task_id": task_id,
                    "file_count": len(clean_files),
                    "eta_minutes": eta,
                    "worker": worker_result,
                    "queued_behind": queued_behind,
                    "sync": sync_result,
                    "message": "Submitted to GB10" if self.runtime_config.mode == "gb10" else "Submitted locally",
                },
            )
        except ValueError as exc:
            return _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            return _json_response(
                self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)}
            )

    def _serve_static(self, name: str, content_type: str | None = None) -> None:
        target = (STATIC_DIR / name).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())):
            return _json_response(self, HTTPStatus.FORBIDDEN, {"error": "Forbidden"})
        if not target.is_file():
            return _json_response(self, HTTPStatus.NOT_FOUND, {"error": f"Missing static asset: {name}"})
        data = target.read_bytes()
        ctype = content_type or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_gui(
    host: str = "127.0.0.1",
    port: int = 8765,
    project: str | None = None,
    runtime: str = "gb10",
    gb10_host: str = "lenovo@100.85.15.59",
    sync_before_go: bool = True,
) -> None:
    """Start the Trias web GUI (blocks until interrupted)."""
    config = load_config()
    runtime_config = RuntimeConfig.from_env(mode=runtime, project=project)
    runtime_config.gb10_host = gb10_host
    runtime_config.sync_before_go = sync_before_go

    TriasGuiHandler.config = config
    TriasGuiHandler.runtime_config = runtime_config
    TriasGuiHandler.runtime = get_runtime(runtime_config)
    TriasGuiHandler.sync_before_go = sync_before_go and runtime == "gb10"

    if runtime == "local":
        TriasGuiHandler.runtime.ensure_mailbox()

    server = ThreadingHTTPServer((host, port), TriasGuiHandler)
    url = f"http://{host}:{port}/"
    print(f"Trias GUI listening on {url}")
    print(f"Runtime: {runtime} ({runtime_config.gb10_host if runtime == 'gb10' else 'local'})")
    print(f"Project root: {runtime_config.project_root}")
    if runtime == "gb10":
        sync_label = "rsync project to GB10 on Go" if sync_before_go else "manual sync before Go"
        print(f"GB10 pdf dir: {runtime_config.pdf_dir} ({sync_label})")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping GUI.")
    finally:
        server.server_close()
