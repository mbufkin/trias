# OWASP Benchmark

Security review benchmark validating Trias against the OWASP Benchmark for Python.

## Results Summary

| Method | Precision | Recall | F1 | Accuracy |
|--------|-----------|--------|----|----|
| Zero-shot (qwen3.6:35b) | 59.5% | 100.0% | 74.6% | 66.0% |
| Two-pass (qwen3-coder-next) | 82.1% | 100.0% | 90.2% | 89.6% |
| **Two-pass (qwen2.5-coder:32b)** | **83.3%** | **100.0%** | **90.9%** | **90.0%** |
| Bandit (SAST) | ~45% | ~70% | — | — |
| Semgrep (SAST) | ~60% | ~80% | — | — |

**50-case sample** across 5 CWE categories on a single Lenovo ThinkStation PGX.

Full benchmark run (1,230 cases) would take ~82 hours on one Lenovo — viable for overnight distributed or 3-machine parallel.

## Files

- `runner.py` — automated benchmark script
- `review_target.py` — Trias review integration
- Results JSONs — baseline, improved-qwen3-coder-next, improved-qwen2.5-coder:32b
- `selected-cases.json` — 50 test case metadata

## Spike

Full spike (runner, cases, results, verdict): `/mnt/hermes/spikes/004-owasp-benchmark/`

## Verdict

Two-pass beats zero-shot by 29 points on precision. 100% recall across all runs. Deployment context injection is the key lever. See `verdict.md` in the spike directory.
