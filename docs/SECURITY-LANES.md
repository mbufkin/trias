# Security lanes — direction

Trias is growing beyond **3-LLM code review**. The goal is **focused lanes**:
one job per command, never “run everything at once” by default.

**Peira** (πεῖρα — trial) is a **separate project** for active probes against live
URLs. Trias does not attack production; Peira does not replace Trias review.

---

## Three lanes

```text
┌─────────────────────────────────────────────────────────────┐
│  TRIAS (this repo)                                          │
│  ├── submit     cognitive — 3 LLMs, synthesis, exploit paths│
│  └── scan       mechanical passive — ONE mode per invocation│
│       ├── static   Bandit (source patterns)                 │
│       ├── deps     pip-audit (supply chain)                 │
│       └── deploy   project smoke script (live/deploy check) │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  PEIRA (separate repo / tool)                               │
│  └── trial      active, unauthenticated probes (--live URL) │
└─────────────────────────────────────────────────────────────┘
```

| Lane | Command (target) | Speed | Needs live app? |
|------|------------------|-------|-----------------|
| Cognitive | `trias submit` | Slow (minutes) | No |
| Static | `trias scan static` | Fast | No |
| Dependencies | `trias scan deps` | Fast | No |
| Deploy | `trias scan deploy` | Medium | Often (smoke / SSH) |
| Active trial | `peira --live …` | Fast | **Yes** |

---

## Design rules

1. **Explicit focus** — `trias scan` requires a mode (`static`, `deps`, or `deploy`).
   No default that runs all three. Optional `trias scan all` only for deliberate
   full passive runs (e.g. nightly CI).

2. **Separate reports** — Each mode writes its own markdown artifact, e.g.
   `{project}-scan-static-{timestamp}.md`, so failures are easy to triage.

3. **Different cadence** — Run `static` + `deps` on code changes; run `deploy`
   before/after shipping to a Pi or tunnel; run `submit` for deep review; run
   Peira rarely (release gate, post-auth refactor).

4. **Trias reviews; Peira trials** — Bandit and pip-audit stay under Trias
   `scan`. HTTP probe logic stays in Peira profiles (e.g. `travel-pdf`).

5. **Project config** — Per-app `.trias.yaml` so Trias stays generic:

   ```yaml
   scan:
     static:
       paths: [app, scripts]
     deps:
       requirements: requirements.txt
     deploy:
       smoke: scripts/smoke_test.py
       smoke_ssh: true
   ```

---

## CLI

```bash
# Cognitive (existing)
trias submit --focus security app/server.py
trias worker &
trias status && trias pull TASK_ID

# Mechanical passive (one mode at a time)
trias scan static  --project /path/to/app
trias scan deps    --project /path/to/app
trias scan deploy  --project /path/to/app   # reads smoke from .trias.yaml

# Optional convenience (not default)
trias scan all     --project /path/to/app

# Active attack — NOT Trias; separate Peira install
peira --live https://example.com/app --profile travel-pdf
```

---

## Current state (2026-06)

| Piece | Status |
|-------|--------|
| `trias submit` / worker / synthesis | **Shipped** |
| `trias scan static\|deps\|deploy\|all` | **Shipped** — one mode per invocation |
| Per-project `.trias.yaml` | **Shipped** — optional; overrides defaults |
| Peira as sibling tool | **Separate codebase**; Travel PDF profile exists |

First consumer app: **CTE Travel PDF** (`pdf-fill-jason` in devhub).

Example targets:

```bash
trias scan deploy --project ../pdf-fill-jason
./scripts/trias-scan.sh static
peira --live https://TUNNEL/travel-pdf --profile travel-pdf
```

---

## Why not one mega-scan?

Static analysis, dependency audit, and deploy smoke fail for **different reasons**
and run on **different schedules**. Combining them:

- Blurs CI logs (“what failed?”)
- Forces deploy checks when you only changed a comment
- Couples offline dev workflows to tunnel/SSH availability

The **triad** idea still applies — three perspectives — but you choose **which
perspective** each time, like choosing `--focus` on `trias submit`.

---

## Related docs

- [README](../README.md) — install, council, OWASP benchmark
- Peira — active trials (separate project; see devhub `tools/peira`)
