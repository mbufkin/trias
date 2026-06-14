#!/usr/bin/env python3
"""
Trias Batch — submit all projects for multi-model review.
Zero babysitting: submits tasks to Lenovo worker, exits.
Worker processes sequentially; results land in ~/.trias/results/.
"""
import subprocess
import sys
import os
import time
from pathlib import Path

os.environ["TRIAS_REMOTE"] = "lenovo"
TRIAS = "/home/mbufkin/.local/bin/trias"

# ── Project definitions: (label, base_dir, file_patterns, focus) ──────────
PROJECTS = [
    # Tier 1 — tiny solo projects, warm up the council
    ("phren", "/home/mbufkin/phren", ["server.py"],
     "FastAPI server — routes, middleware, error handling, security"),
    ("london-tutor-fork", "/home/mbufkin/london-tutor-fork", ["server.py"],
     "Flask tutoring server — auth, session management, SQL injection, XSS"),
    ("thinkstation-benchmark", "/home/mbufkin/thinkstation-px-benchmark",
     ["benchmark.py", "benchmark_v2.py", "benchmark_final.py"],
     "LLM benchmarking — subprocess safety, JSON parsing, timing accuracy, resource cleanup"),

    # Tier 2 — small multi-file projects
    ("compute-scrapers", "/home/mbufkin/compute/jobs",
     ["advanced_scraper.py", "flight_price_framework.py", "points_tracker.py",
      "price_monitor.py", "simple_scraper.py"],
     "Job scrapers — web scraping ethics, rate limiting, error handling, data validation"),
    ("web-scraping", "/home/mbufkin/projects/web-scraping/scrapers",
     ["improved_finder.py", "scheduler.py", "transfer_screenshots.py",
      "points_calculator.py", "browser_helper.py", "quick_entry.py",
      "batch_import.py", "deal_tracker.py"],
     "Web scraping toolkit — Selenium/Playwright safety, auth handling, data integrity"),
    ("hatc-automation", "/home/mbufkin/projects",
     ["hatc/mail_room.py", "automation/example_automation.py"],
     "HATC mail room + automation — task routing, error recovery, idempotency"),

    # Tier 3 — Can Freedom (NCMEC)
    ("ncmec-core", "/home/mbufkin/ncmec-missing",
     ["generate.py", "generate_html.py", "ncmec_poster_api.py",
      "distribution_mapper.py", "sync.py", "_utils.py"],
     "NCMEC Can Freedom — PDF generation, ArcGIS integration, data pipelines, API safety"),
    ("ncmec-tests", "/home/mbufkin/ncmec-missing",
     ["test_2page.py", "test_legal.py", "test_production_2page.py",
      "test_recent.py", "test_sync.py", "compare_sources.py"],
     "NCMEC test suite — test coverage, edge cases, async safety, fixture cleanup"),

    # Tier 4 — Hermes Agent (large, batched by module)
]

# ── Hermes Agent modules — each is a batch ─────────────────────────────────
HERMES_AGENT = "/mnt/hermes/hermes-agent"
def find_py(dir_path, exclude=None):
    """Find all .py files in dir, excluding specified substrings in path."""
    files = []
    for f in Path(dir_path).rglob("*.py"):
        s = str(f)
        if exclude and any(x in s for x in exclude):
            continue
        files.append(s)
    return sorted(files)

HERMES_MODULES = [
    ("hermes-core-agent", find_py(f"{HERMES_AGENT}/agent", ["__pycache__", "skills"])[:25],
     "Hermes core agent — message routing, context management, tool dispatch, safety guards"),
    ("hermes-tools", find_py(f"{HERMES_AGENT}/tools", ["__pycache__", "skills"])[:25],
     "Hermes tools — file ops, terminal, web, browser, delegation, security boundaries"),
    ("hermes-cli", find_py(f"{HERMES_AGENT}/hermes_cli", ["__pycache__"])[:25],
     "Hermes CLI — arg parsing, config loading, subprocess safety, signal handling"),
    ("hermes-gateway", find_py(f"{HERMES_AGENT}/gateway", ["__pycache__", "skills"])[:25],
     "Hermes gateway — platform adapters, message serialization, auth, rate limiting"),
    ("hermes-plugins", find_py(f"{HERMES_AGENT}/plugins", ["__pycache__", "skills", "node_modules"])[:25],
     "Hermes plugins — extension system, memory backends, third-party integrations"),
    ("hermes-transports-lsp", find_py(f"{HERMES_AGENT}/agent/transports", ["__pycache__"]) +
                           find_py(f"{HERMES_AGENT}/agent/lsp", ["__pycache__"]),
     "Hermes transports + LSP — subprocess management, code intelligence, protocol safety"),
    ("hermes-acp-tui", find_py(f"{HERMES_AGENT}/acp_adapter", ["__pycache__"]) +
                       find_py(f"{HERMES_AGENT}/tui_gateway", ["__pycache__"]),
     "Hermes ACP + TUI — agent communication protocol, terminal UI, input sanitization"),
    ("hermes-env-tools", find_py(f"{HERMES_AGENT}/tools/environments", ["__pycache__"]) +
                         find_py(f"{HERMES_AGENT}/tools/computer_use", ["__pycache__"]),
     "Hermes environments — sandboxing, container isolation, computer-use safety"),
]


def submit(project_name, base_dir, files, focus, batch_num=None):
    """Submit a batch of files for review. Returns task_id or None."""
    label = f"{project_name}{f'-{batch_num}' if batch_num else ''}"

    # Verify files exist
    existing = []
    for f in files:
        full = os.path.join(base_dir, f) if not os.path.isabs(f) else f
        if os.path.exists(full):
            # Use relative path from base_dir
            existing.append(os.path.relpath(full, base_dir) if not os.path.isabs(f) else f)
        else:
            print(f"  ⚠️  Missing: {full}")

    if not existing:
        print(f"  ❌ No files found for {label}")
        return None

    # Build focus string
    full_focus = f"[{label}] {focus}"

    cmd = [TRIAS, "submit", "--focus", full_focus] + existing
    try:
        result = subprocess.run(
            cmd, cwd=base_dir, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            task_id = None
            for line in result.stdout.split("\n"):
                if line.startswith("Submitted:"):
                    task_id = line.split(":")[1].strip()
            print(f"  ✅ {label}: {task_id} ({len(existing)} files)")
            return task_id
        else:
            print(f"  ❌ {label}: {result.stderr[:200]}")
            return None
    except Exception as e:
        print(f"  ❌ {label}: {e}")
        return None


def main():
    print("=" * 60)
    print("TRIAS BATCH — Fire and Forget")
    print(f"Target: lenovo (TRIAS_REMOTE=lenovo)")
    print(f"Worker: running on ThinkStation PGX")
    print(f"Estimated: ~15-20 batches, ~2-3 hours each = 30-60 hours total")
    print("=" * 60)

    task_ids = []
    total_files = 0

    # Submit tiered projects
    for name, base_dir, files, focus in PROJECTS:
        print(f"\n── {name} ──")
        tid = submit(name, base_dir, files, focus)
        if tid:
            task_ids.append((name, tid))
            total_files += len(files)
        time.sleep(2)  # gentle spacing between submissions

    # Submit Hermes Agent modules
    for name, files, focus in HERMES_MODULES:
        if not files:
            print(f"\n── {name} ── (no files, skipping)")
            continue
        print(f"\n── {name} ({len(files)} files) ──")
        tid = submit(name, HERMES_AGENT, files, focus)
        if tid:
            task_ids.append((name, tid))
            total_files += len(files)
        time.sleep(2)

    print("\n" + "=" * 60)
    print(f"SUBMITTED: {len(task_ids)} batches, ~{total_files} files")
    print(f"Estimated runtime: {len(task_ids) * 6}–{len(task_ids) * 10} minutes")
    print()
    print("Task queue:")
    for name, tid in task_ids:
        print(f"  {name:<30} {tid}")
    print()
    print("Monitor with:")
    print("  TRIAS_REMOTE=lenovo trias status")
    print("  ssh lenovo 'tail -f /home/lenovo/.trias/worker.log'")
    print()
    print("Pull all results when done:")
    print("  for tid in $(ssh lenovo 'ls /home/lenovo/.trias/results/*.md' | xargs -n1 basename | sed 's/.md//'); do")
    print("    TRIAS_REMOTE=lenovo trias pull $tid --output /home/mbufkin/trias-reviews/")
    print("  done")
    print("=" * 60)


if __name__ == "__main__":
    main()
