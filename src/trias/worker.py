#!/usr/bin/env python3
"""
Review Council Worker — polls for review tasks, runs multi-model council,
writes synthesized reports.

Key features:
- Sequential model cycling with keep_alive=0 to free GPU memory
- HTTP via urllib (stdlib) — no shell subprocess, no injection surface
- Timeouts on all HTTP calls (fixes hung requests)
- Empty-response detection (treats as failure)
- Continues if a reviewer fails — noted in synthesis
- Synthesis by the strongest model
- Status tracking at every stage
- Task archive after completion
- Architectural glossary from Matt Pocock's deep module framework
- FileLockAdapter — stateless seam for concurrency control
"""

import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config

logger = logging.getLogger("trias")


def ensure_dirs(config: dict):
    for key in ["tasks", "status", "results", "archive", "uploads"]:
        Path(config["paths"][key]).mkdir(parents=True, exist_ok=True)


class FileLockAdapter:
    """Stateless seam for POSIX advisory file locking.

    Replaces the old acquire_lock/release_lock function-attribute hack.
    Encapsulates the lock file descriptor and exposes acquire/release
    as a clean interface — testable, no global mutable state.
    """

    def __init__(self, lock_path: str):
        self._path = lock_path
        self._fd = None

    def acquire(self) -> bool:
        """Try to acquire an exclusive lock. Returns True on success."""
        import fcntl
        try:
            self._fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o644)
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.write(self._fd, str(os.getpid()).encode())
            os.fsync(self._fd)
            return True
        except (OSError, IOError):
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            return False

    def release(self):
        """Release the lock and close the file descriptor."""
        import fcntl
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None


def ollama_unload(config: dict, model: str):
    """Tell Ollama to unload a model to free GPU memory."""
    payload = json.dumps({"model": model, "prompt": "done", "keep_alive": 0}).encode()
    url = f"{config['ollama']['url']}/api/generate"
    try:
        req = urllib.request.Request(url, data=payload, method="POST")
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:
        logger.warning("Failed to unload %s: %s", model, e)


def ollama_generate(config: dict, model: str, prompt: str,
                    timeout: int = 240, num_predict: int = 1536,
                    temperature: float = 0.3) -> str:
    """Call Ollama generate API via urllib. Returns response text or raises.

    Uses urllib.request (stdlib, no shell) — avoids the curl subprocess
    injection surface. All data flows through JSON-encoded request bodies.
    """
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }).encode()
    url = f"{config['ollama']['url']}/api/generate"

    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ollama HTTP {e.code}: {e.read().decode()[:200]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach Ollama: {e.reason}")
    except json.JSONDecodeError:
        raise RuntimeError("Ollama returned non-JSON response")

    if "error" in data:
        raise RuntimeError(f"Ollama error: {data['error']}")
    return data.get("response", "")


def validate_model(model: str) -> bool:
    """Validate model name against strict whitelist: alphanumeric, dots, hyphens, colons, underscores.
    Max 128 chars. No shell metacharacters, path separators, or whitespace."""
    import re
    return bool(re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", model))


def check_model_health(config: dict, model: str, timeout: int = 30,
                       retries: int = 3, backoff_base: float = 0.5) -> bool:
    """Quick health ping with retry and jittered backoff for transient failures."""
    if not validate_model(model):
        logger.warning("Model name failed validation: %s", model)
        return False

    payload = json.dumps({
        "model": model, "prompt": "ping", "stream": False,
        "options": {"num_predict": 1},
    }).encode()
    url = f"{config['ollama']['url']}/api/generate"

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=payload, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
                if data.get("response", "").strip():
                    return True
        except Exception as e:
            if attempt < retries - 1:
                delay = backoff_base * (2 ** attempt) + (time.time() % 1)
                logger.debug("Health check retry %d/%d for %s in %.1fs: %s",
                            attempt + 1, retries, model, delay, e)
                time.sleep(delay)
            else:
                logger.warning("Health check failed for %s after %d attempts: %s",
                              model, retries, e)
    return False


def validate_council(config: dict) -> list[dict]:
    """Check all council models are healthy. Returns list of healthy reviewers."""
    healthy = []
    for reviewer in config.get("council", []):
        model = reviewer["model"]
        label = reviewer.get("label", model)
        if check_model_health(config, model):
            healthy.append(reviewer)
            logger.info("✓ %s — %s", model, label)
        else:
            logger.warning("✗ %s — %s (SKIPPED: unhealthy)", model, label)
    return healthy


def read_files(file_paths: list[str], base_dir: str, max_chars: int = 5000) -> str:
    """Read and concatenate files for review. Paths relative to base_dir."""
    base = Path(base_dir).resolve()
    chunks = []
    for fp in file_paths:
        full = (base / fp).resolve()
        if not full.is_relative_to(base):
            chunks.append(f"=== {fp} ===\n[BLOCKED: path escapes base directory]")
            continue
        try:
            content = full.read_text()
            if len(content) > max_chars:
                content = content[:max_chars] + f"\n... [truncated from {len(content)} chars]"
            chunks.append(f"=== {fp} ===\n{content}")
        except FileNotFoundError:
            chunks.append(f"=== {fp} ===\n[not found]")
        except Exception as e:
            chunks.append(f"=== {fp} ===\n[error: {e}]")
    return "\n\n".join(chunks)


def write_status(config: dict, task_id: str, status: str, **extra):
    data = {"task_id": task_id, "status": status,
            "updated": datetime.now(timezone.utc).isoformat(), **extra}
    (Path(config["paths"]["status"]) / f"{task_id}.json").write_text(
        json.dumps(data, indent=2))


# Architectural review glossary — based on Matt Pocock's deep module framework
# https://youtu.be/3MP8D-mdheA
_ARCH_GLOSSARY = (
    "SHARED VOCABULARY — apply these concepts in your review:\n"
    "- Module: a unit of functionality (component group, service, logger, etc.)\n"
    "- Deep module: hides lots of implementation behind a simple interface (high leverage)\n"
    "- Shallow module: complex interface with little implementation behind it (low leverage)\n"
    "- Interface: everything a caller must know to use the module correctly\n"
    "- Seam: the location where a module's interface lives — where testing/mocking happens\n"
    "- Adapter: a concrete module that satisfies an interface (e.g., real clock vs fake clock)\n"
    "- Locality: changes and fixes concentrated in one place (good) vs scattered (bad)\n"
    "- Leverage: capability gained per unit of interface learned (deep = high leverage)\n"
    "\n"
)


def process_task(config: dict, task_path: Path) -> bool:
    """Process a single review task. Returns True on success."""
    task_id = task_path.stem
    write_status(config, task_id, "started")

    try:
        task = json.loads(task_path.read_text())
    except json.JSONDecodeError as e:
        write_status(config, task_id, "failed", error=f"Invalid JSON: {e}")
        return False

    files = task.get("files", [])
    focus = task.get("focus", config["review"]["focus"])
    base_dir = Path(task.get("base_dir", str(Path.home()))).expanduser().resolve()
    council = task.get("council") or config.get("_healthy_council") or config["council"]
    syn_config = config["synthesis"]
    rev_config = config["review"]

    if not files:
        write_status(config, task_id, "failed", error="No files specified")
        return False

    code = read_files(files, str(base_dir), rev_config["max_file_chars"])
    if not code.strip():
        write_status(config, task_id, "failed", error="All files empty or not found")
        return False

    # === RUN COUNCIL ===
    reviews = []
    prev_model = None

    for i, reviewer in enumerate(council):
        model = reviewer["model"]
        label = reviewer.get("label", model)
        n = i + 1
        total = len(council)

        if prev_model:
            ollama_unload(config, prev_model)
            time.sleep(3)

        write_status(config, task_id, "reviewing", round=n, total=total,
                     model=model, label=label)

        prompt = (
            f"Code review — Round {n} of {total}. Review this code thoroughly.\n\n"
            + _ARCH_GLOSSARY
            + f"CODE:\n{code}\n\n"
            + f"Focus on: {focus}.\n"
            + "For each finding: severity (HIGH/MEDIUM/LOW), file:line, category, description.\n"
            + "Flag shallow modules that could be deepened. Identify seams that could be better defined.\n"
            + "Be specific and critical. Be concise. Do not praise — find problems."
        )

        try:
            t0 = time.time()
            response = ollama_generate(config, model, prompt,
                                       timeout=config["ollama"]["timeout_per_model"],
                                       num_predict=rev_config["num_predict"],
                                       temperature=rev_config["temperature"])
            elapsed = time.time() - t0
            if not response or not response.strip():
                raise RuntimeError("Empty response from model")
            reviews.append({
                "model": model, "label": label, "round": n,
                "response": response, "elapsed_s": round(elapsed, 1),
                "chars": len(response),
            })
            print(f"  Round {n}/{total} {model}: {elapsed:.0f}s, {len(response)} chars",
                  flush=True)
        except Exception as e:
            print(f"  Round {n}/{total} {model}: FAILED — {e}", flush=True)
            reviews.append({
                "model": model, "label": label, "round": n,
                "response": f"[FAILED: {e}]", "elapsed_s": 0, "chars": 0,
            })

        prev_model = model

    if prev_model:
        ollama_unload(config, prev_model)
        time.sleep(3)

    # === SYNTHESIS ===
    write_status(config, task_id, "synthesizing")

    all_reviews = "\n\n---\n\n".join(
        f"## Reviewer {r['round']}: {r['label']} ({r['model']})\n{r['response'][:2500]}"
        for r in reviews
    )

    synth_prompt = (
        f"Synthesize these {len(reviews)} independent code reviews into one final report.\n\n"
        + _ARCH_GLOSSARY
        + f"CODE:\n{code[:2500]}\n\n"
        + f"REVIEWS:\n{all_reviews[:5000]}\n\n"
        + "Your output:\n"
        + "## 🔴 CONSENSUS (flagged by 2+ reviewers)\n"
        + "[table: severity, issue, files, reviewers]\n"
        + "\n"
        + "## 🟡 UNIQUE INSIGHTS (important, only one reviewer)\n"
        + "[table: reviewer, finding, significance]\n"
        + "\n"
        + "## 🛠️ PRIORITY RANKING (top 5 must-fix)\n"
        + "[numbered list with rationale]"
    )

    try:
        t0 = time.time()
        synthesis = ollama_generate(config, syn_config["model"], synth_prompt,
                                    timeout=config["ollama"]["synthesis_timeout"],
                                    num_predict=syn_config["num_predict"],
                                    temperature=syn_config["temperature"])
        synth_elapsed = time.time() - t0
    except Exception as e:
        synthesis = f"[SYNTHESIS FAILED: {e}]"
        synth_elapsed = 0

    # === BUILD REPORT ===
    total_time = sum(r["elapsed_s"] for r in reviews) + synth_elapsed
    succeeded = sum(1 for r in reviews if not r["response"].startswith("[FAILED"))
    failed = len(reviews) - succeeded

    ok_icon = "⚠️" if failed else "✅"
    report = f"""# Code Review — {task_id}

**Files:** {', '.join(files)}
**Focus:** {focus}
**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

## Council ({succeeded}/{len(reviews)} reviewers succeeded, {ok_icon}{' ' + str(failed) + ' failed' if failed else ''} all clear)

### Reviewers
"""
    for r in reviews:
        ok = not r["response"].startswith("[FAILED")
        icon = "✅" if ok else "❌"
        report += f"- {icon} **{r['label']}** — `{r['model']}` — {r['elapsed_s']}s, {r['chars']} chars\n"

    report += f"\n---\n\n## Synthesis ({synth_elapsed:.0f}s)\n\n{synthesis}\n"
    report += f"\n---\n\n*Total: {total_time:.0f}s | Council: {succeeded}/{len(reviews)} | Synthesis: {syn_config['model']}*"

    report += "\n\n---\n\n## Raw Reviews (full text)\n\n"
    for r in reviews:
        report += f"### Reviewer {r['round']}: {r['label']}\n{r['response']}\n\n---\n\n"

    result_path = Path(config["paths"]["results"]) / f"{task_id}.md"
    result_path.write_text(report)

    meta = {
        "task_id": task_id, "status": "completed",
        "files": files, "focus": focus,
        "succeeded": succeeded, "failed": failed,
        "total_time_s": round(total_time, 1),
        "synthesis_model": syn_config["model"],
        "council": [{"model": r["model"], "label": r["label"],
                      "elapsed_s": r["elapsed_s"]} for r in reviews],
        "completed": datetime.now(timezone.utc).isoformat(),
    }
    (Path(config["paths"]["status"]) / f"{task_id}.json").write_text(
        json.dumps(meta, indent=2))

    task_path.rename(Path(config["paths"]["archive"]) / task_path.name)
    print(f"  Done: {result_path} ({total_time:.0f}s total)", flush=True)
    return True


def run_worker(config_path: str | None = None):
    """Main loop — poll for tasks and process them."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s",
                        stream=sys.stderr)

    config = load_config(config_path)
    ensure_dirs(config)

    mailbox = config["paths"]["mailbox"]
    tasks_dir = Path(config["paths"]["tasks"])
    poll_interval = config["review"]["poll_interval"]

    lock = FileLockAdapter(str(Path(mailbox) / "worker.lock"))
    if not lock.acquire():
        print("Another worker is running. Exiting.", flush=True)
        sys.exit(0)

    print(f"Review Council Worker — polling {tasks_dir} every {poll_interval}s",
          flush=True)

    healthy = validate_council(config)
    if not healthy:
        logger.error("No healthy models available — exiting.")
        lock.release()
        sys.exit(1)
    config["_healthy_council"] = healthy
    print(f"Models: {len(healthy)}/{len(config.get('council',[]))} healthy", flush=True)

    try:
        while True:
            tasks = sorted(tasks_dir.glob("*.json"))
            if tasks:
                task_path = tasks[0]
                task_id = task_path.stem
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] {task_id}", flush=True)
                try:
                    process_task(config, task_path)
                except Exception as e:
                    print(f"  FATAL: {e}", flush=True)
                    write_status(config, task_id, "failed", error=str(e))
                    try:
                        task_path.rename(
                            Path(config["paths"]["archive"]) / f"{task_id}.failed.json")
                    except Exception:
                        pass
            time.sleep(poll_interval)
    finally:
        lock.release()


if __name__ == "__main__":
    run_worker()
