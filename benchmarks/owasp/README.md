# OWASP Benchmark — LLM Security Review Validation

**Trias is a multi-model code review engine. This benchmark validates its Security Reviewer role.**

Trias has three focused roles — Security, Architecture, and Correctness — each with independently reviewable principles. The OWASP Benchmark for Python validates the Security role's performance: data-flow tracing, exploit chain construction, sink classification, and input verification.

We benchmarked our single-model reviewer (qwen3.6:35b-a3b) against the [OWASP Benchmark for Python](https://github.com/OWASP-Benchmark/BenchmarkPython) — 50 hand-crafted test cases across five vulnerability categories. Each case is either genuinely vulnerable or safely written to look dangerous. The benchmark measures whether an LLM can tell the difference.

The question: can we build a prompt that catches every real vulnerability without drowning in false positives?

## Methodology

Every case was reviewed by the **same model** (qwen3.6:35b-a3b) on the **same hardware** (Lenovo ThinkStation PGX, 119GB RAM, CPU-only). The only variable: the prompt.

### Baseline prompt

> *"Review this Python code for security vulnerabilities. Output VULNERABLE: YES or VULNERABLE: NO."*

A single-pass, zero-shot security review. The model did what models do — flagged everything that looked dangerous.

### Improved prompt

Three changes:

1. **Category locking** — the prompt specifies exactly which vulnerability to check (e.g., "Check for Command Injection, CWE-78. Ignore XSS, CSRF, and other categories.")

2. **Data-flow trace requirement** — the model must trace user input from source to sink, step by step, checking for overwrites and dead branches before rendering a verdict.

3. **Explicit overwrite check** — the prompt calls out the most common false-positive pattern: "Check if the variable gets overwritten by a hardcoded value before reaching the sink."

## Results

| Metric | Baseline | Improved | Delta |
|--------|----------|----------|-------|
| **True Positives** | 25 | 25 | — |
| **False Positives** | 17 | **4** | −13 |
| **False Negatives** | 0 | 0 | — |
| **True Negatives** | 8 | 21 | +13 |
| **Precision** | 59.5% | **86.2%** | +26.7pp |
| **Recall** | 100% | **100%** | — |
| **F1** | 0.746 | **0.926** | +0.180 |

## What We Learned

### The baseline model isn't bad — it's just undisciplined

100% recall means qwen3.6:35b-a3b never misses a real vulnerability. The problem is signal-to-noise: at 59.5% precision, every other alert is a false alarm. That's exhausting for a human reviewer and erodes trust fast.

### Data-flow tracing eliminates 76% of false positives

The prompt didn't get smarter — it got more specific. By forcing the model to trace user input step by step, we eliminated 13 of 17 false positives:

- **Command Injection (cmdi)**: 4 FPs → **0**. Every safe case used `shell=True` with a hardcoded string — the model now catches the overwrite before the sink.
- **Insecure Deserialization**: 4 FPs → **0**. Same pattern — `map['keyB'] = param` then `bar = map['keyA']` (hardcoded). The trace catches the reassignment.
- **SQL Injection**: 2 FPs → **0**. The baseline flagged XSS in SQLi tests. Category locking fixed this.
- **Path Traversal**: 3 FPs → **2**. Still the hardest category — the model sometimes treats URL parsing as a taint path.
- **Code Injection**: 4 FPs → **2**. Complex conditional branches still confuse it.

### The 4 remaining false positives

| Test Case | Category | Root Cause |
|-----------|----------|------------|
| BenchmarkTest01111 | Path Traversal | `get_safe_value()` function name misleads the model — assumes sanitization |
| BenchmarkTest00908 | Path Traversal | Query string parsing + URL decoding looks like a live taint path |
| BenchmarkTest01164 | Code Injection | Same `get_safe_value()` naming trick |
| BenchmarkTest00892 | Code Injection | Conditional branch analysis error — can't resolve at inference time |

Two are fooled by a function literally named `get_safe_value()` (it's a no-op in the benchmark). The other two require runtime branch resolution the model can't do in a single pass.

### The model is the ceiling — not the prompt

At 86.2% precision with 100% recall, we're near the limit of what prompt engineering alone can achieve on a 35B model. Further gains would require a second-pass triage model, execution-based verification, or a larger model — the 120B class we're exploring with distributed inference across multiple Lenovos.

## Reproducing

**Requirements:**
- Python 3.10+
- Ollama running with qwen3.6:35b-a3b pulled
- SSH access to the machine running Ollama (or run locally)
- OWASP Benchmark for Python test cases

**Setup:**
```bash
# Clone the OWASP Benchmark for Python
git clone https://github.com/OWASP-Benchmark/BenchmarkPython.git

# Install Trias benchmark runner
cd trias/benchmarks/owasp

# Edit runner.py to point to your Ollama instance
# Default: lenovo@localhost:11434

# Run baseline
python3 runner.py baseline

# Run improved
python3 runner.py improved
```

Each run takes ~33 minutes for 50 cases. Results are saved as JSON in `results/`.

## Hardware

All benchmarks run on a **Lenovo ThinkStation PGX**:
- 20-core ARM CPU (10× Cortex-X925 @ 3.9 GHz + 10× Cortex-A725 @ 2.8 GHz)
- 119 GB unified memory
- No discrete GPU — pure CPU inference
- qwen3.6:35b-a3b (MoE) at ~73 tok/s

This is a $5,000 consumer-grade machine, not a datacenter GPU node. The entire benchmark costs ~$0 in API fees.

## Related

- [Distributed inference research](../distributed-inference-research.md) — pooling multiple Lenovos to run 70B-120B models
- [Trias](../) — the multi-model code review engine this benchmark validates
- [OWASP Benchmark for Python](https://github.com/OWASP-Benchmark/BenchmarkPython)

## License

MIT
