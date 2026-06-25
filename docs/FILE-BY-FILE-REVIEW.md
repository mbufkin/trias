# File-by-file review

Trias **`submit`** reviews code **one file at a time** by default. This prevents
large submissions from being skimmed or “whitewashed” — where the model glances at
file 1, fixates on one finding, and never really reads files 2–N.

Peira and `trias scan` are unrelated; this doc is only for **`trias submit`**.

---

## How it works

When you pass multiple files:

```bash
trias submit app/security.py app/routes.py app/jobs.py --focus security
```

Trias runs the **full council on each file in order**:

```text
File 1/3: app/security.py
  → Reviewer 1 (full file + checklist)
  → Reviewer 2 (full file + checklist)
  → Reviewer 3 (full file + checklist)

File 2/3: app/routes.py
  → Reviewer 1 …
  …

File 3/3: app/jobs.py
  → …

→ Synthesis (all files, grouped by path)
→ Skeptic gate (disprove findings)
```

Each reviewer sees **only the current file** (up to `review.max_file_chars`, default
12 000). They must complete a **mandatory checklist** before finishing:

1. **ENTRY** — untrusted input sources  
2. **FLOWS** — trace input to sinks in this file  
3. **SINKS** — SQL, shell, files, auth, deserialization  
4. **EDGES** — null/empty, errors, races  
5. **TRUST** — imports that change trust boundaries  

If nothing is wrong, they must say **`CLEAN: path/to/file`** and what they verified —
not a vague “looks fine.”

---

## Why not one big blob?

| Problem | One combined prompt | Sequential (default) |
|--------|---------------------|----------------------|
| Skimming | Model reads start of file 1, skips rest | One file = full attention budget |
| Fixation | One flashy bug hides others | Each file gets its own pass |
| Truncation | 5k chars × N files mashed together | 12k chars **per file** |
| Coverage proof | Hard to know file 7 was read | Report lists every file + CLEAN markers |

---

## Report sections

1. **File coverage** — every submitted path, reviewers OK per file  
2. **Synthesis** — includes **FILE COVERAGE** table (quiet files listed explicitly)  
3. **Skeptic gate** — attacks consolidated findings  
4. **Raw reviews** — grouped by file for audit trail  

---

## Configuration

In `config.yaml` (or `~/.config/trias/config.yaml`):

```yaml
review:
  # sequential (default) | batch (legacy — all files in one prompt)
  file_strategy: sequential
  max_file_chars: 12000          # per file during council
  synthesis_chars_per_file: 4000 # re-read cap for synthesis/skeptic
```

Use **`batch`** only for tiny submissions (2 small files, quick smoke review).

---

## Best practices

1. **List files explicitly** — don’t rely on globs that pull in 40 files at once.  
   Batch by concern: auth, routes, PDF logic, etc.

2. **Order matters** — submit entry points first (`security.py`, `routes.py`), then
   helpers.

3. **Watch status** — `trias status` shows `file_index/file_total` and `current_file`
   while the worker runs.

4. **Check FILE COVERAGE in synthesis** — if a file is missing from the table,
   something went wrong; re-submit that file alone.

5. **Deep review ≠ scan** — Bandit/pip-audit stay under `trias scan`.  
   Live CTF-style probes stay under **Peira**.

---

## Example (Travel PDF)

```bash
cd pdf-fill-jason
trias submit \
  app/security.py \
  app/routes.py \
  app/jobs.py \
  --focus security
```

Expect ~3 council rounds × 3 files = **9 review rounds** before synthesis — slower,
but each file gets a real look.
