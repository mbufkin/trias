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

Runs entirely on local hardware via Ollama. No cloud, no API keys, no data
exfiltration.

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
```

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

## Hardware

Trias is designed to run on local, consumer-grade AI hardware. Below are
real-world benchmarks from the machines it's been tested on.

> **OWASP Benchmark validation:** See [benchmarks/owasp](benchmarks/owasp/) for
> the full security review benchmark — 86.2% precision, 100% recall on the
> OWASP Benchmark for Python using a single Lenovo ThinkStation PGX.

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
| **Ollama** | 7 models loaded (19–65 GB each) |

**Performance (measured tok/s):**

| Model | Size | Quant | Eval Rate |
|-------|------|-------|-----------|
| qwen3-coder-next | 51 GB | q4_K_M | **59.1 tok/s** |
| qwen2.5-coder:32b | 19 GB | — | 10.0 tok/s |
| qwen3.6:35b-a3b (MoE) | 23 GB | — | ~73 tok/s |
| gpt-oss:120b | 65 GB | — | ⚠️ locks GPU; not usable |

**Typical review latency:** ~3–4 minutes per submission (3 models ×
~60s each, including load/unload + synthesis).

### Tower (Custom Build) — *benchmarks pending*

Custom workstation, also ARM64 aarch64, serving Ollama and ComfyUI.
Full specs and Trias benchmarks coming soon.

### Running on Smaller Hardware

Trias cycles models sequentially — only one model is loaded at a time.
You need enough GPU memory for your *largest* single model, not the sum
of all three. On a machine with 24 GB VRAM, choose smaller quants or
lighter models in `config.yaml`.

Minimum recommended: **16 GB VRAM** (for 7–8B models at Q4).

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) with models pulled
- GPU memory: enough for your largest single model (see Hardware above)

## Configuration

```bash
trias init          # writes config.yaml with defaults
```

Edit `config.yaml` to customize models, paths, Ollama endpoint, timeouts.

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
