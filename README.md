# Trias

**Local-first multi-model code review — three LLMs, one report.**

Your code goes in. Three different models review it independently. Their
findings are synthesized into one prioritized, actionable report. Nothing
leaves your machine.

> *τρίας (trias)* — Ancient Greek for "a group of three." The three reviewers
> form a triad, each seeing what the others miss. The synthesis *triages*
> findings by severity. Three models, three perspectives, one truth.

## Why

Single-model code review is an echo chamber. Each model architecture has
blind spots. Trias runs three *different* architectures against your code —
MoE agentic, dense base, dense OpenCode-tuned — and synthesizes the overlap
and unique insights.

Runs entirely on local hardware via **llama.cpp** (`llama-server`). No cloud,
no API keys, no data exfiltration.

## Security lanes (direction)

Trias is **not one tool that does everything at once**. It is splitting into
**focused lanes**:

| Lane | What | Command |
|------|------|---------|
| **Cognitive review** | 3 LLMs, synthesis, exploit paths | `trias submit` |
| **Passive scan** | Mechanical checks, **one mode per run** | `trias scan static\|deps\|deploy` |
| **Active trial** | Live URL probes | **[Peira](docs/SECURITY-LANES.md#three-lanes)** — separate project |

- **`submit`** — deep code review; use `--focus security` (or performance, etc.).
  **Default: one file at a time** through the full council (see
  [FILE-BY-FILE-REVIEW.md](docs/FILE-BY-FILE-REVIEW.md)) so large submissions
  are not skimmed.
- **`scan`** — fast passive checks; **requires a mode** (`static`, `deps`, or `deploy`).
  Optional `scan all` for deliberate full passive runs (CI/nightly only).
- **Peira** — attacker / trial tool; Trias never sends active probes to prod.

Full rationale and examples: **[docs/SECURITY-LANES.md](docs/SECURITY-LANES.md)**.

**GB10 hardware test:** **[docs/GB10-TEST.md](docs/GB10-TEST.md)** — sync to Lenovo PGX and run sequential file review.

```bash
# Cognitive review
trias submit --focus security app/server.py

# Passive scan — one mode per run (optional .trias.yaml in project root)
trias scan static --project /path/to/app
trias scan deps   --project /path/to/app
trias scan deploy --project /path/to/app

# CI convenience only
trias scan all --project /path/to/app

# Separate tool — active trials
peira --live https://your-app.example --profile travel-pdf
```

## Quick Start

```bash
pip install trias

# Start the worker daemon
trias worker &

# Submit code for review
trias submit --wait src/*.py

# With a custom timeout (default: 900s)
trias submit --wait --timeout 300 *.py

# Or submit and check back later
trias submit --focus "security, performance" server.py
trias status
trias pull 20260613-092041-abc12345

# Web GUI — GB10 control panel (Go button, live logs, multi-hour runs)

Prerequisites on GB10: Gemma on `:8080`, Tailscale up. **Go rsyncs your Mac project to `~/pdf-fill-jason` automatically** (disable with checkbox or `trias gui --no-sync`).

```bash
pip install -e ~/tools/trias

# From your Mac (browse local project, submit to GB10)
trias gui \
  --runtime gb10 \
  --project ~/Documents/Coding/devhub/tools/pdf-fill-jason \
  --gb10-host lenovo@100.85.15.59

# Open http://127.0.0.1:8765/
# Click Go — checks Gemma, starts worker if needed, submits, shows live progress + log tail
```

| GUI feature | Behavior |
|-------------|----------|
| **Go** | rsync project → GB10 → check llama → start worker → submit |
| **All files** | Toggle off extension filter; paste paths manually |
| **Live panel** | File/reviewer progress, ETA, worker log tail (polls GB10 over SSH) |
| **Queue** | Per-item position, ETA, and wait time (polls every 5s) |
| **Completed tab** | Cards with HIGH/MED counts and clean vs needs-attention badge |
| **Triage** | Action items (consensus + priority, skeptic-filtered), file coverage, dismissed findings |
| **Full report** | Collapsible sections: Priority, Consensus, Skeptic, Raw reviews |

### Reading a report in the GUI

1. **While running** — live panel shows progress; triage opens automatically when status hits `completed`.
2. **After the fact** — sidebar **Completed** tab → **Triage** (action list) or **Full** (markdown sections).
3. **CLI fallback** — `trias pull TASK_ID --output .` writes `review-TASK_ID.md` locally.

### Report API (for scripts / future Telegram)

```bash
# List completed reviews with severity summary
curl -s http://127.0.0.1:8765/api/reports | python3 -m json.tool

# Structured triage payload (action_items, file_coverage, sections, markdown)
curl -s http://127.0.0.1:8765/api/reports/TASK_ID | python3 -m json.tool

# Legacy — raw markdown only
curl -s http://127.0.0.1:8765/api/results/TASK_ID
```

New runs write a JSON sidecar at `~/.trias/results/{TASK_ID}.json` on GB10 (parsed at write time). Older reports fall back to on-demand markdown parsing.

Local-only runtime: `trias gui --runtime local` (requires local llama + worker).

## How It Works

1. **Submit** — `trias submit file1.py file2.js` drops a task in the mailbox
2. **Review** — Worker picks it up, cycles 3 models sequentially (unloading
   between to fit in GPU memory). Each reviewer must construct a concrete
   exploit chain for HIGH-severity findings — pattern matching alone doesn't cut it.
3. **Verify** — Synthesizer challenges every consensus finding: "Can I
   actually construct an exploit path from this?" Findings that can't be
   exploited are downgraded or discarded.
4. **Report** — Markdown report with verified findings, exploit chains for
   HIGHs, and priority-ranked fixes.

## Default Council

| Reviewer | Model | Architecture | Strength |
|----------|-------|-------------|----------|
| R1 | qwen3-coder-next | MoE agentic | Systems, security, correctness |
| R2 | qwen2.5-coder:32b | Dense 32B base | Code logic, edge cases |
| R3 | qwen2.5-coder-opencode | Dense 32B OpenCode | Patterns, refactoring, tests |

All configurable in `config.yaml`.

> **Dogfooded:** Trias reviews its own code before every push. The council
> catches real issues — but it can also flag false positives (pattern matching
> without execution-model understanding). Every finding gets human verification.
> Trias is a second set of eyes, not a replacement for your own.

## OWASP Benchmark — Independent Security Validation

Trias has been validated against the [OWASP Benchmark for Python](https://github.com/OWASP-Benchmark/BenchmarkPython) —
1,230 hand-crafted test cases spanning 11 vulnerability categories including
path traversal, SQL injection, XSS, weak cryptography, and command injection.
Every test case has a known ground truth: it IS vulnerable or it is NOT.

The benchmark tests whether Trias can distinguish real vulnerabilities from
safe code that *looks* suspicious — the hardest problem in static analysis.

**Full run — 1,230 cases, single Lenovo ThinkStation PGX (32B-class models):**

| Metric | Trias | Bandit (static analysis) |
|---|---|---|
| **Precision** | **92.9%** | 0.0% |
| **Recall** | 55.1% | 0.0% |
| **F1 Score** | 69.2% | 0.0% |
| **Accuracy** | 81.9% | 63.3% |
| **True Positives** | 249 | 0 |
| **False Positives** | 19 | 0 |
| **False Negatives** | 203 | 452 |

**What this means:**

- **When Trias says something is vulnerable, it's right 92.9% of the time.**
  Only 19 false positives across 1,230 test cases. The verify phase —
  which requires concrete exploit chain construction for every confirmed
  finding — filters out the noise that plagues traditional static analysis.
  Bandit, by comparison, flagged nothing at all.

- **55% recall means there's room to grow.** 203 vulnerabilities slipped
  through. Some categories (weak randomness, certain injection patterns)
  are harder for 32B-class models to catch consistently. The architecture
  supports swapping in larger models as hardware allows — the same council
  with 70B+ models is expected to close much of this gap.

- **This runs where API keys can't go.** No cloud. No data exfiltration.
  No third-party dependency. A single workstation in a school district IT
  closet, a hospital server room, or an air-gapped facility can run the
  same pipeline.

> **Methodology:** 3-pass council — FLAG (initial security scan) →
> CHALLENGE (independent second model cross-checks every finding) →
> VERIFY (exploit chain construction required for confirmation).
> Full results and per-case verdicts in [benchmarks/owasp/full-run/](benchmarks/owasp/full-run/).

## Hardware

Trias is designed to run on local, consumer-grade AI hardware. Below are
real-world benchmarks from the machines it's been tested on.

### Lenovo ThinkStation PGX (Primary)

| Spec | Detail |
|------|--------|
| **Model** | ThinkStation PGX (30KL0002US) |
| **CPU** | 20-core ARM — 10× Cortex-X925 @ 3.9 GHz + 10× Cortex-A725 @ 2.8 GHz |
| **GPU** | NVIDIA GB10 (Grace Blackwell) — unified memory architecture |
| **RAM** | 119 GiB unified memory |
| **Storage** | 1 TB NVMe SSD |
| **OS** | Ubuntu 24.04, kernel 6.17, aarch64 |
| **CUDA** | 13.0 |
| **Inference** | llama.cpp `llama-server` (see [docs/LLAMA-CPP.md](docs/LLAMA-CPP.md)) |

**Typical review latency:** depends on GGUF size and context; Gemma 4 31B on
GB10 is ~30–60s per council round with synthesis + skeptic on the same server.

### Tower (Custom Build) — *benchmarks pending*

Custom workstation, also ARM64 aarch64.

### Running on Smaller Hardware

One `llama-server` loads one GGUF at a time. You need enough GPU memory for
that model's quant. Use smaller GGUFs or lower context in `serve-cuda.sh`.

Minimum recommended: **16 GB VRAM** (for 7–8B models at Q4).

## Requirements

- Python 3.10+
- **llama.cpp** `llama-server` with OpenAI API (`/v1/chat/completions`)
- GPU memory for your loaded GGUF (see [docs/LLAMA-CPP.md](docs/LLAMA-CPP.md))

## Configuration

```bash
cp config.example.yaml ~/.trias/config.yaml   # or trias init
```

Edit `config.yaml` — set `llamacpp.url` and model ids from `GET /v1/models`.

## Remote Worker

For split setups (submit from one machine, run on another with GPUs):

```bash
export TRIAS_REMOTE="gpu-box.local"
trias submit --wait *.py   # scp's to remote, pulls results back
```

The Lenovo ThinkStation PGX above runs the Trias worker as a systemd user
service, accepting submissions from the dev machine over Tailscale.

## The Name

*Trias* (τρίας) is Ancient Greek for a group of three — the Pythagoreans
considered three the first true number, the principle of multiplicity.
Three reviewers, three perspectives, one synthesis. The English "triage"
descends from the same root: sorting by priority, which is exactly what
the synthesis report does.

## Development Workflow: PRD + Trias Gate

Trias development itself follows a Ralph-inspired workflow: small, testable
user stories with machine-readable pass/fail flags, append-only progress
logging, and Trias as the pre-commit quality gate.

### PRD format (`prd.json`)

Each feature is a user story with a `passes` flag — no ambiguity about
what "done" means:

```json
[
  {
    "id": 1,
    "story": "trias submit rejects files over 2MB with a clear error",
    "passes": false,
    "test": "echo 'x' | trias submit --stdin big-file.py → exit 1"
  },
  {
    "id": 2,
    "story": "council models configurable via TRIAS_COUNCIL env var",
    "passes": true
  }
]
```

One feature per iteration. Mark `passes: true` when done (with tests).
This keeps the AI and the human aligned on exactly what success looks like.

### Progress log (`progress.txt`)

Append-only inter-session memory. After each feature, the developer
(or agent) appends what was learned — gotchas, fragile areas, context
the next session will need:

```
2026-06-13 — added ollama_generate timeout (30s). 
Model unload on the PGX takes 8-12s; don't shorten the 
unload wait below 10s or you'll get partial loads. 
GPU locks at 120B — never accidentally pull that model.
```

Delete `progress.txt` when the sprint is done. Until then, it's cheap
persistent memory that works with any model.

### Pre-push gate

Before pushing, run Trias against the diff:

```bash
# Review staged changes
trias submit --diff HEAD~1 --wait

# Or set up a pre-push hook
cat > .git/hooks/pre-push << 'EOF'
#!/bin/bash
echo "Trias reviewing $(git diff --stat origin/main)..."
trias submit --diff origin/main --wait --threshold MEDIUM
if [ $? -ne 0 ]; then
  echo "Trias found MEDIUM+ issues. Push blocked."
  exit 1
fi
EOF
chmod +x .git/hooks/pre-push
```

Trias reviewing its own code before every push. The council catches
what a single-model review misses.

## License

MIT
