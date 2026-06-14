# Distributed LLM Inference on Consumer Hardware
## Research notes — June 2026

### Context
Goal: run models too large for a single Lenovo PGX (119GB RAM, CPU-only, no GPU)
by pooling 3-4 Lenovos connected via a managed switch.

### Three viable projects

#### 1. prima.cpp
- **Paper:** arxiv.org/abs/2504.08791 (April 2025)
- **Code:** gitee.com/zonghang-li/prima.cpp
- **Designed for:** heterogeneous home clusters with CPU, slow disks, Wi-Fi
- **Key tech:** Pipelined-Ring Parallelism (PRP) — overlaps disk I/O, compute, and network
- **Benchmarks on 4 consumer devices:**
  - 70B model: 1.5 tok/s (<6% memory pressure)
  - 32B model: 26 tok/s (with speculative decoding)
- **vs others:** 5-17× faster than llama.cpp RPC, broader OS/quant support
- **Bottom line:** The research pick. Built for exactly our use case.

#### 2. exo (exo-explore/exo)
- **GitHub:** github.com/exo-explore/exo — 21K+ stars, Apache 2.0
- **Key features:** auto-discovers devices, splits models, OpenAI-compatible API, dashboard
- **On Linux: CPU-only** (GPU support in development)
- **Benchmarks on Mac Studio clusters:**
  - DeepSeek v3.1 671B (8-bit) across 4 × M3 Ultra
  - Qwen3-235B (8-bit) across 4 × M3 Ultra
  - RDMA over Thunderbolt 5 for fast interconnect
- **Bottom line:** The polished pick. Active development, good docs.

#### 3. distributed-llama (b4rtaz/distributed-llama)
- **GitHub:** github.com/b4rtaz/distributed-llama — MIT
- **Key features:** tensor parallelism over ethernet, one-command launch
- **Scales:** 2^n workers (1 root + 1, 3, 7 workers)
- **Pre-configured models:** Qwen3 (0.6B-30B A3B), Llama 3.1 (8B-405B), DeepSeek R1
- **Supports:** ARM + x86_64, Linux/macOS/Windows
- **Bottom line:** The simplest pick. `python launch.py` and go.

### Expected performance on our hardware

| Setup | Speed | Notes |
|---|---|---|
| qwen3.6:35b-a3b on 1 Lenovo | 73 tok/s | Current baseline |
| 70B model via prima.cpp on 3 Lenovos | 1-3 tok/s | Network-bound |
| 120B model via prima.cpp/exo on 3 Lenovos | 0.5-1 tok/s | Viable for overnight batch |
| 32B coders × 3 in parallel (per-box) | ~30 tok/s each | Best throughput, no network overhead |

### The parallel route
Running independent 32-35B models on each Lenovo reviewing different files,
then merging findings = near-linear speedup with zero network tensor overhead.
More practical than one big slow model for code review use case.

### Network
Managed switch with fast ethernet is the key enabler.
Without it, tensor distribution is bottlenecked by link speed.
Thunderbolt/RDMA is faster but Apple-only (exo on macOS).
Prima.cpp's PRP specifically addresses network latency by overlapping with disk I/O.

### Next steps (when ready)
1. Test exo discovery on 2 Lenovos (no model load, just cluster formation)
2. Benchmark prima.cpp with a 70B model on 2-3 Lenovos
3. Compare parallel 32B vs distributed 70B for code review quality vs speed

### Not worth pursuing
- llama.cpp vanilla RPC: functional but slow, prima.cpp is strictly better
- vLLM multi-node: requires GPUs, not CPU-only
- Cloud API comparison: different use case (privacy, cost predictability)
