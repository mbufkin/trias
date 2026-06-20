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


def _truncate_lines(text: str, max_chars: int) -> str:
    """Truncate to complete lines only — never cut mid-line or mid-function.

    Returns the text if under max_chars. Otherwise returns complete lines
    up to max_chars, reserving space for the omission note so total output
    never exceeds max_chars.
    """
    if len(text) <= max_chars:
        return text
    lines = text.rstrip("\n").split("\n")
    result = []
    total = 0
    # Reserve space for the omission note line
    note_template = "\n[... {count} lines omitted — full file available to reviewers above]"
    # Estimate worst-case note size (assume up to 9999 lines = 4 digits)
    note_budget = len(note_template.format(count=9999))
    usable = max_chars - note_budget
    for i, line in enumerate(lines):
        nl = 1 if i < len(lines) - 1 else 0
        if total + len(line) + nl > usable:
            break
        result.append(line)
        total += len(line) + nl
    omitted = len(lines) - len(result)
    note = note_template.format(count=omitted)
    result.append(note)
    return "\n".join(result)


class FPMemory:
    """Persistent false-positive memory — learns which patterns are safe.

    Semgrep Multimodal inspired: tracks findings verified as NOT exploitable
    across scans. Injected into synthesis to prevent re-flagging known FPs.

    Stores in a JSON file at the configured mailbox path.
    """

    def __init__(self, memory_path: str):
        self._path = Path(memory_path)
        self.entries: list[dict] = []
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                text = self._path.read_text()
                if not text.strip():
                    self.entries = []
                    return
                data = json.loads(text)
                self.entries = data.get("entries", [])
            except (json.JSONDecodeError, KeyError):
                self.entries = []

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(
            {"entries": self.entries, "updated": datetime.now(timezone.utc).isoformat()},
            indent=2)
        # Atomic write: write to temp then rename — prevents corruption on crash
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            mode="w", dir=str(self._path.parent), delete=False,
            prefix=".fp_memory", suffix=".tmp")
        try:
            tmp.write(content)
            tmp.close()
            os.replace(tmp.name, str(self._path))  # atomic on POSIX
        except Exception:
            Path(tmp.name).unlink(missing_ok=True)
            raise

    def add(self, pattern: str, claimed_issue: str, verdict: str,
            file_pattern: str = "", code_snippet: str = ""):
        """Record a finding verified as false positive."""
        # Normalize to prevent FP pollution from case/whitespace variations
        norm_pattern = pattern.strip().lower()
        norm_file = file_pattern.strip().lower()
        norm_verdict = verdict.strip()

        # Deduplicate — same pattern + same file = skip
        for entry in self.entries:
            if (entry.get("pattern", "").strip().lower() == norm_pattern and
                    entry.get("file_pattern", "").strip().lower() == norm_file):
                entry["reflag_count"] = entry.get("reflag_count", 0) + 1
                entry["last_reflagged"] = datetime.now(timezone.utc).isoformat()
                self._save()
                return

        entry = {
            "id": f"fp_{len(self.entries) + 1:03d}",
            "pattern": pattern,
            "file_pattern": file_pattern,
            "code_snippet": code_snippet[:200] if code_snippet else "",
            "claimed_issue": claimed_issue[:200],
            "actual_verdict": verdict.strip()[:300],
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "reflag_count": 0,
            "last_reflagged": None,
        }
        self.entries.append(entry)
        logger.info("FP memory: recorded '%s' (%s)", pattern, verdict[:80])
        self._save()

    def format_for_prompt(self) -> str:
        """Format FP entries for injection into the synthesis prompt."""
        if not self.entries:
            return ""

        lines = [
            "PREVIOUSLY VERIFIED FALSE POSITIVES — these patterns were flagged",
            "in past reviews but verified as NOT exploitable. If the current",
            "reviewers flag the same patterns again, you may skip or auto-downgrade",
            "them. Reference the FP ID in your verification note.\n",
        ]
        for entry in self.entries[-10:]:  # last 10, most relevant
            lines.append(
                f"  [{entry['id']}] {entry['pattern']}\n"
                f"      Claimed: {entry['claimed_issue']}\n"
                f"      Verdict: {entry['actual_verdict']}\n"
                f"      File: {entry['file_pattern'] or 'any'}\n"
                f"      Reflagged: {entry['reflag_count']} times\n"
            )
        return "\n".join(lines)

    def extract_and_record(self, synthesis_text: str):
        """Parse synthesis output for findings verified as NOT exploitable,
        and record them as FP memories."""
        import re

        # Catch "Verdict: NOT exploitable" or "Verdict: not exploitable"
        fp_matches = re.findall(
            r'(?:Verdict|verdict)[:\s]*.*?(NOT\s+exploitable[^.\n|]*)',
            synthesis_text, re.IGNORECASE
        )
        # Catch "overstates risk" / "concern ... over-stated"
        overstate_matches = re.findall(
            r'(?:overstates?\s+risk|over-?stated)[^.\n]*\.',
            synthesis_text, re.IGNORECASE
        )
        # Catch explicit downgrades: "downgrade to MEDIUM" or "downgraded to LOW"
        downgrade_matches = re.findall(
            r'downgrad(?:ed?|ing)\s+to\s+(MEDIUM|LOW)[^.\n]*\.',
            synthesis_text, re.IGNORECASE
        )

        for match in fp_matches:
            self.add(
                pattern="(extracted from synthesis verdict)",
                claimed_issue="(see synthesis report)",
                verdict=f"NOT exploitable: {match.strip()[:250]}",
            )

        for match in overstate_matches:
            self.add(
                pattern="(extracted from verification note)",
                claimed_issue="(see synthesis report)",
                verdict=f"Overstated: {match.strip()[:250]}",
            )

        for match in downgrade_matches:
            self.add(
                pattern="(extracted from downgrade note)",
                claimed_issue="(see synthesis report)",
                verdict=f"Downgraded to {match.strip()[:250]}",
            )


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
    """Check all council models are healthy. Mode-aware: checks focused_roles
    when review.mode == 'focused', otherwise checks the council list.
    Returns list of healthy reviewers."""
    mode = config.get("review", {}).get("mode", "council")

    if mode == "focused":
        roles = config.get("focused_roles", {})
        candidates = [
            {"model": rc["model"], "label": rc["label"]}
            for rc in roles.values()
        ]
    else:
        candidates = config.get("council", [])

    healthy = []
    for reviewer in candidates:
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


def _verify_exploit_chains(synthesis: str) -> str:
    """Scan synthesis for HIGH/CRITICAL findings that lack exploit chain evidence.

    Adkins ([un]prompted 2026): every HIGH severity claim must include a
    concrete exploit path. Without one, it's pattern-matching, not a real
    finding. This function appends a downgrade warning to the synthesis
    if any HIGH findings are missing trace evidence.

    Returns empty string if all HIGH findings have traces, or a downgrade
    note to append to the synthesis.
    """
    import re

    # Find the CONSENSUS section
    consensus_start = synthesis.find("## 🔴 CONSENSUS")
    if consensus_start < 0:
        return ""

    # Extract the section — search for next ## heading or end
    consensus_text = synthesis[consensus_start:]
    next_heading = re.search(r"\n##\s", consensus_text[3:])  # skip the heading itself
    if next_heading:
        consensus_text = consensus_text[:next_heading.start() + 3]

    # Find table rows with severity markers
    # Table format: | severity | issue | files | reviewers | trace_summary |
    high_findings = re.findall(
        r'\|\s*\*{0,2}(HIGH|CRITICAL)\*{0,2}\s*\|(.*?)(?=\n\||\n\n|\Z)',
        consensus_text, re.IGNORECASE | re.DOTALL
    )

    if not high_findings:
        return ""

    downgrades = []
    for severity, row in high_findings:
        # Row format after severity: issue | files | reviewers | trace_summary
        cols = [c.strip() for c in row.split("|")]
        trace_col = cols[3] if len(cols) >= 4 else ""

        # Evidence of a real trace: source→sink walkthrough, hop-by-hop,
        # concrete inputs, exploit path markers
        has_trace = any(marker in trace_col.lower() for marker in [
            "source:", "hop ", "sink:", "exploit", "verdict:",
            "attacker", "→", "->",
        ])

        # Evidence of NO real trace: empty, placeholder, generic description
        is_empty = len(trace_col) < 30
        is_placeholder = any(p in trace_col.lower() for p in [
            "none", "n/a", "not applicable", "see above",
        ])

        if is_empty or (is_placeholder and not has_trace) or (not is_empty and not has_trace):
            # Extract the issue description
            issue = cols[1] if len(cols) > 1 else "unknown issue"
            downgrades.append(f"  - **{severity}**: {issue[:100]}")

    if not downgrades:
        return ""

    note = (
        "\n\n---\n\n"
        "## ⚠️ PROOF-OF-VULNERABILITY CHECK\n\n"
        "_The following findings are flagged as HIGH/CRITICAL but lack "
        "a concrete exploit chain (source → hop → sink walkthrough, "
        "specific attacker input, or verifiable execution path). "
        "Per [un]prompted 2026 (Adkins/Flynn): pattern matching without "
        "a working exploit path is not a verified vulnerability._\n\n"
        "**Downgrade to MEDIUM unless an exploit chain is provided:**\n\n"
        + "\n".join(downgrades) + "\n"
    )
    return note


def _file_checklist(code: str) -> str:
    """Generate a numbered file checklist for the prompt.

    Carlini ([un]prompted 2026): LLMs fixate on one vulnerability and miss others
    in large codebases. Explicit file-by-file checkpointing forces the model to
    address every file in order before moving on.

    Only activates when 2+ files are present. Single-file reviews don't need it.
    """
    import re
    files = re.findall(r'=== (.+?) ===', code)
    if len(files) <= 1:
        return ""
    return (
        "FILES TO REVIEW (in order — do NOT skip any):\n"
        + "\n".join(f"  [{i}] {f}" for i, f in enumerate(files, 1))
        + "\n\nCRITICAL: Review each file separately. After completing analysis of a file,\n"
        + "output '✓ FILE COMPLETE: [filename]' before moving to the next file.\n"
        + "This ensures you do not fixate on one finding and miss others.\n\n"
    )


def build_focused_prompt(role_config: dict, principles_registry: dict,
                         code: str, round_n: int, total: int) -> str:
    """Build a role-specific review prompt from principles.

    Each principle in the role's principles list is resolved from the
    principles registry and injected into the prompt. Principles are
    independently reviewable and updatable in config.yaml.
    """
    principle_names = role_config.get("principles", [])
    label = role_config.get("label", "Reviewer")

    # Resolve principles from registry
    resolved = []
    for name in principle_names:
        p = principles_registry.get(name, {})
        if p:
            resolved.append(f"### {p.get('name', name)}\n{p.get('prompt', '').strip()}")
        else:
            resolved.append(f"### {name}\n[principle not found in registry]")

    principles_text = "\n\n".join(resolved) if resolved else "(no principles configured)"

    prompt = (
        f"Code review — Round {round_n} of {total}. "
        f"You are the **{label}**. Review ONLY through this lens.\n\n"
        + _file_checklist(code)
        + f"CODE:\n{code}\n\n"
        + f"=== YOUR PRINCIPLES ===\n\n"
        + f"{principles_text}\n\n"
        + f"=== OUTPUT FORMAT ===\n"
        + f"For each finding: severity (HIGH/MEDIUM/LOW), file:line, principle, description.\n"
        + f"Be specific and critical. Do not praise — find problems.\n"
        + f"Stay within your role. If you notice issues outside your domain, "
        + f"trust that another reviewer will catch them."
    )
    return prompt

def build_council_prompt(code: str, focus: str, round_n: int, total: int) -> str:
    """Build the general council review prompt (backward compatible)."""
    prompt = (
        f"Code review — Round {round_n} of {total}. Review this code thoroughly.\n\n"
        + _ARCH_GLOSSARY
        + _file_checklist(code)
        + f"CODE:\n{code}\n\n"
        + f"Focus on: {focus}.\n"
        + "For each finding: severity (HIGH/MEDIUM/LOW), file:line, category, description.\n"
        + "IMPORTANT: For any HIGH severity finding, you MUST include a concrete exploit chain "
        + "(specific input → code path → harm). If you cannot construct one, it is NOT HIGH.\n"
        + "Pattern matching is not enough — verify against the actual execution model.\n"
        + "Flag shallow modules that could be deepened. Identify seams that could be better defined.\n"
        + "Be specific and critical. Be concise. Do not praise — find problems."
    )
    return prompt


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

    # Load persistent FP memory to avoid re-flagging known false positives
    fp_memory_path = Path(config["paths"]["mailbox"]) / "fp_memory.json"
    fp_memory = FPMemory(str(fp_memory_path))

    # === RUN COUNCIL ===
    reviews = []
    prev_model = None
    rev_mode = rev_config.get("mode", "council")

    # Build reviewer list based on mode
    if rev_mode == "focused":
        focused_roles = config.get("focused_roles", {})
        principles_registry = config.get("principles", {})
        reviewers = [
            {"model": rc["model"], "label": rc["label"],
             "role_config": rc, "is_focused": True}
            for rc in focused_roles.values()
        ]
    else:
        reviewers = [
            {"model": r["model"], "label": r.get("label", r["model"]),
             "role_config": None, "is_focused": False}
            for r in council
        ]

    for i, reviewer in enumerate(reviewers):
        model = reviewer["model"]
        label = reviewer["label"]
        n = i + 1
        total = len(reviewers)

        if prev_model:
            ollama_unload(config, prev_model)
            time.sleep(3)

        write_status(config, task_id, "reviewing", round=n, total=total,
                     model=model, label=label)

        if reviewer["is_focused"]:
            prompt = build_focused_prompt(
                reviewer["role_config"], principles_registry, code, n, total)
        else:
            prompt = build_council_prompt(code, focus, n, total)

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
        f"## Reviewer {r['round']}: {r['label']} ({r['model']})\n{_truncate_lines(r['response'], 2500)}"
        for r in reviews
    )

    synth_prompt = (
        f"Synthesize these {len(reviews)} independent code reviews into one final report.\n\n"
        + _ARCH_GLOSSARY
        + fp_memory.format_for_prompt()
        + f"\nCODE:\n{_truncate_lines(code, 5000)}\n\n"
        + f"REVIEWS:\n{all_reviews[:5000]}\n\n"
        + "CRITICAL — Before reporting any finding, verify it:\n\n"
        + "STEP 1 — TRACE THE DATA FLOW (for taint/injection findings):\n"
        + "  Walk EVERY hop from source to sink. At each hop, ask: what sanitization,\n"
        + "  validation, or transformation is applied? Format:\n"
        + "    Source: [where does untrusted data enter?]\n"
        + "    Hop 1: [function call] → [sanitization applied?]\n"
        + "    Hop 2: [function call] → [sanitization applied?]\n"
        + "    ...\n"
        + "    Sink: [where is data used? command? HTTP? DB? file?]\n"
        + "    Verdict: [exploitable / not exploitable / uncertain]\n\n"
        + "STEP 2 — CHECK THE SINK TYPE:\n"
        + "  - Shell command? Critical — any unsanitized input = RCE.\n"
        + "  - SQL query? Critical — check for parameterization.\n"
        + "  - File path? Check for traversal (../) and absolute path escapes.\n"
        + "  - HTTP URL? Check SSRF risk, but downgrade if internal-only or trusted domains.\n"
        + "  - Log/print? Usually LOW — informational leak at worst.\n\n"
        + "STEP 3 — CHECK THE EXECUTION MODEL:\n"
        + "  - Is a shell involved? (subprocess with shell=True, os.system, backticks)\n"
        + "  - Are args list-based? (subprocess.run(['cmd', arg]) — NO shell, semicolons inert)\n"
        + "  - Is input validated? (regex whitelist, type check, allowlist)\n"
        + "  - Is input source-restricted? (config constant vs user input vs API response)\n\n"
        + "If you cannot complete the trace OR the sink is low-risk, it is NOT HIGH.\n"
        + "Downgrade to MEDIUM or LOW and note why.\n"
        + "Pattern matching alone (e.g., 'string in f-string = injection') is not enough.\n\n"
        + "Your output:\n"
        + "## 🔴 CONSENSUS (flagged by 2+ reviewers, VERIFIED with trace)\n"
        + "[table: severity, issue, files, reviewers, trace_summary]\n"
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

    # === PROOF-OF-VULNERABILITY VERIFIER ===
    # Adkins ([un]prompted 2026): eliminate false positives by requiring
    # every HIGH finding to include a concrete exploit chain. If the
    # synthesis model flags something HIGH but didn't actually walk the
    # data flow, auto-downgrade it. This is a safety net — the synthesis
    # prompt already asks for traces, but models sometimes skip them.
    if synthesis and not synthesis.startswith("[SYNTHESIS FAILED"):
        downgrade_notes = _verify_exploit_chains(synthesis)
        if downgrade_notes:
            synthesis += downgrade_notes

    # === SKEPTIC GATE ===
    # After synthesis, a skeptical model tries to DISPROVE each finding.
    # This is adversarial reflection (FENRIR pattern): if the skeptic can
    # construct a benign explanation or show the exploit path is broken,
    # the finding is marked DISPUTED. Findings that survive skepticism
    # have higher confidence. Inspired by [un]prompted 2026 talks:
    #   - FENRIR: "adversarial reflection / disproof agent"
    #   - Rami McCarthy: "AI never questions the abstraction you give it"
    #   - Joshua Saxe: "the noise ceiling" — expert disagreement is real
    skeptic_config = config.get("skeptic", {})
    skeptic_enabled = skeptic_config.get("enabled", False)
    skeptic_model = skeptic_config.get("model", syn_config["model"])
    skeptic_elapsed = 0
    skeptic_response = ""

    if skeptic_enabled and synthesis and not synthesis.startswith("[SYNTHESIS FAILED") and code.strip():
        write_status(config, task_id, "skeptic_check")

        skeptic_prompt = (
            "You are a SKEPTICAL SECURITY AUDITOR. Your job is to DISPROVE every\n"
            "finding in the synthesis below. Assume every finding is a FALSE POSITIVE\n"
            "until you can construct a working exploit. Do NOT agree with the reviewers\n"
            "— find flaws in their analysis.\n\n"
            "For each finding in the synthesis, answer:\n"
            "1. Does user-controlled input ACTUALLY reach the dangerous sink?\n"
            "   Walk the data flow explicitly. If any hop breaks the chain → DISPROVEN.\n"
            "2. Is there a sanitization, validation, or transformation the reviewers missed?\n"
            "3. Is the finding pattern-matching (\"f-string = SQLi\") without a real exploit path?\n"
            "4. Could this be intentional / by-design behavior?\n\n"
            "OUTPUT FORMAT — one verdict per finding:\n"
            "DISPROVEN: [finding description] — [specific reason with code evidence]\n"
            "STANDS: [finding description] — [why the skeptic cannot disprove it]\n\n"
            f"ORIGINAL CODE:\n{_truncate_lines(code, 4000)}\n\n"
            f"SYNTHESIS TO DISPROVE:\n{_truncate_lines(synthesis, 3000)}\n"
        )

        try:
            t0 = time.time()
            skeptic_response = ollama_generate(
                config, skeptic_model, skeptic_prompt,
                timeout=skeptic_config.get("timeout", 180),
                num_predict=skeptic_config.get("num_predict", 1024),
                temperature=skeptic_config.get("temperature", 0.2),
            )
            skeptic_elapsed = time.time() - t0
            if not skeptic_response or not skeptic_response.strip():
                skeptic_response = "[Skeptic returned empty response]"
            print(f"  Skeptic ({skeptic_model}): {skeptic_elapsed:.0f}s, {len(skeptic_response)} chars", flush=True)
        except Exception as e:
            skeptic_response = f"[SKEPTIC FAILED: {e}]"
            print(f"  Skeptic: FAILED — {e}", flush=True)

        # Unload skeptic model to free GPU memory
        if skeptic_model:
            ollama_unload(config, skeptic_model)
            time.sleep(2)

    # === BUILD REPORT ===
    total_time = sum(r["elapsed_s"] for r in reviews) + synth_elapsed + skeptic_elapsed
    succeeded = sum(1 for r in reviews if not r["response"].startswith("[FAILED"))
    failed = len(reviews) - succeeded

    ok_icon = "⚠️" if failed else "✅"
    mode_label = "Focused Review" if rev_mode == "focused" else "Council"
    skeptic_label = " + Skeptic Gate" if (skeptic_enabled and skeptic_response) else ""
    report = f"""# Code Review — {task_id}

**Files:** {', '.join(files)}
**Mode:** {mode_label}{skeptic_label}
**Focus:** {focus}
**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

## {mode_label} ({succeeded}/{len(reviewers)} reviewers succeeded, {ok_icon}{' ' + str(failed) + ' failed' if failed else ''} all clear)

### Reviewers
"""
    for r in reviews:
        ok = not r["response"].startswith("[FAILED")
        icon = "✅" if ok else "❌"
        report += f"- {icon} **{r['label']}** — `{r['model']}` — {r['elapsed_s']}s, {r['chars']} chars\n"

    report += f"\n---\n\n## Synthesis ({synth_elapsed:.0f}s)\n\n{synthesis}\n"

    # Append skeptic gate section if it ran
    if skeptic_enabled and skeptic_response:
        dispute_count = skeptic_response.count("DISPROVEN:") if skeptic_response else 0
        stands_count = skeptic_response.count("STANDS:") if skeptic_response else 0
        report += f"\n---\n\n## 🛡️ Skeptic Gate ({skeptic_model}, {skeptic_elapsed:.0f}s)\n\n"
        report += f"_Adversarial disproof check — findings survive only if skeptic cannot disprove._\n\n"
        report += f"**Disproven: {dispute_count}** | **Stands: {stands_count}**\n\n"
        report += f"{skeptic_response}\n"

    report += f"\n---\n\n*Total: {total_time:.0f}s | {mode_label}: {succeeded}/{len(reviewers)} | Synthesis: {syn_config['model']}*"

    report += "\n\n---\n\n## Raw Reviews (full text)\n\n"
    for r in reviews:
        report += f"### Reviewer {r['round']}: {r['label']}\n{r['response']}\n\n---\n\n"

    result_path = Path(config["paths"]["results"]) / f"{task_id}.md"
    result_path.write_text(report)

    # Extract verified false positives from synthesis for future scans
    fp_memory.extract_and_record(synthesis)

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
    if skeptic_enabled and skeptic_response:
        meta["skeptic"] = {
            "model": skeptic_model,
            "elapsed_s": round(skeptic_elapsed, 1),
            "disproven_count": skeptic_response.count("DISPROVEN:") if skeptic_response else 0,
            "stands_count": skeptic_response.count("STANDS:") if skeptic_response else 0,
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
