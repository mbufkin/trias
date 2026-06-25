"""Parse Trias review markdown into structured triage data for API and GUI."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Section headings emitted by synthesis (worker.py prompt).
_HEADING_CONSENSUS = re.compile(
    r"^##\s*🔴\s*CONSENSUS", re.IGNORECASE | re.MULTILINE
)
_HEADING_UNIQUE = re.compile(
    r"^##\s*🟡\s*UNIQUE\s*INSIGHTS", re.IGNORECASE | re.MULTILINE
)
_HEADING_PRIORITY = re.compile(
    r"^##\s*🛠️\s*PRIORITY\s*RANKING", re.IGNORECASE | re.MULTILINE
)
_HEADING_FILE_COVERAGE = re.compile(
    r"^##\s*📁\s*FILE\s*COVERAGE", re.IGNORECASE | re.MULTILINE
)
_HEADING_SYNTHESIS = re.compile(r"^##\s*Synthesis\s*\(", re.MULTILINE)
_HEADING_SKEPTIC = re.compile(r"^##\s*🛡️\s*Skeptic\s*Gate", re.MULTILINE)
_HEADING_RAW = re.compile(r"^##\s*Raw\s*Reviews", re.MULTILINE)

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "ARCH": 4}


def parse_report_markdown(
    markdown: str,
    *,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Parse a Trias `.md` report into structured JSON-serializable data."""
    text = markdown.strip()
    if not text:
        raise ValueError("Empty report markdown")

    parsed_task_id = task_id or _extract_task_id(text)
    meta = _parse_meta(text, parsed_task_id)
    sections = _split_sections(text)

    file_coverage = _parse_file_coverage_table(
        sections.get("file_coverage_md", "")
    )
    consensus = _parse_consensus_table(sections.get("consensus_md", ""))
    unique_insights = _parse_unique_table(sections.get("unique_md", ""))
    priority = _parse_priority_list(sections.get("priority_md", ""))
    skeptic_verdicts = _parse_skeptic_verdicts(sections.get("skeptic_md", ""))

    dismissed, action_items = _build_action_items(
        consensus, priority, skeptic_verdicts
    )
    summary = _build_summary(
        consensus, file_coverage, skeptic_verdicts, action_items
    )

    return {
        "task_id": parsed_task_id,
        "meta": meta,
        "summary": summary,
        "file_coverage": file_coverage,
        "consensus": consensus,
        "priority": priority,
        "unique_insights": unique_insights,
        "skeptic_verdicts": skeptic_verdicts,
        "dismissed_by_skeptic": dismissed,
        "action_items": action_items,
        "sections": {
            "synthesis": sections.get("synthesis_md", ""),
            "consensus_md": sections.get("consensus_md", ""),
            "priority_md": sections.get("priority_md", ""),
            "unique_md": sections.get("unique_md", ""),
            "skeptic_md": sections.get("skeptic_md", ""),
            "raw_reviews_md": sections.get("raw_reviews_md", ""),
        },
    }


def parse_report_file(path: Path, *, task_id: str | None = None) -> dict[str, Any]:
    """Load and parse a report from disk."""
    text = path.read_text(encoding="utf-8")
    tid = task_id or path.stem.removeprefix("review-")
    return parse_report_markdown(text, task_id=tid)


def report_list_summary(parsed: dict[str, Any]) -> dict[str, Any]:
    """Compact summary for GET /api/reports list responses."""
    meta = parsed.get("meta") or {}
    summary = parsed.get("summary") or {}
    return {
        "task_id": parsed.get("task_id"),
        "status": "completed",
        "completed": meta.get("completed"),
        "files": meta.get("files") or [],
        "focus": meta.get("focus") or "",
        "summary": summary,
        "needs_attention": summary.get("needs_attention", False),
    }


def _extract_task_id(text: str) -> str:
    m = re.search(r"^#\s*Code Review\s*—\s*(\S+)", text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    raise ValueError("Could not extract task_id from report header")


def _parse_meta(text: str, task_id: str) -> dict[str, Any]:
    meta: dict[str, Any] = {"task_id": task_id}
    files_m = re.search(r"^\*\*Files:\*\*\s*(.+)$", text, re.MULTILINE)
    if files_m:
        meta["files"] = [f.strip() for f in files_m.group(1).split(",") if f.strip()]
    mode_m = re.search(r"^\*\*Mode:\*\*\s*(.+)$", text, re.MULTILINE)
    if mode_m:
        meta["mode"] = mode_m.group(1).strip()
    focus_m = re.search(r"^\*\*Focus:\*\*\s*(.+)$", text, re.MULTILINE)
    if focus_m:
        meta["focus"] = focus_m.group(1).strip()
    date_m = re.search(r"^\*\*Date:\*\*\s*(.+)$", text, re.MULTILINE)
    if date_m:
        meta["date"] = date_m.group(1).strip()
    total_m = re.search(r"\*Total:\s*([\d.]+)s", text)
    if total_m:
        meta["total_time_s"] = float(total_m.group(1))
    return meta


def _find_section(text: str, start_pat: re.Pattern[str]) -> tuple[int, int]:
    """Return (start, end) indices for a section body (excluding heading line)."""
    m = start_pat.search(text)
    if not m:
        return -1, -1
    start = m.end()
    # Next ## heading at same or higher level ends this section.
    nxt = re.search(r"\n##\s", text[start:])
    end = start + nxt.start() if nxt else len(text)
    return start, end


def _split_sections(text: str) -> dict[str, str]:
    """Split report into named markdown chunks."""
    out: dict[str, str] = {}

    syn_m = _HEADING_SYNTHESIS.search(text)
    sk_m = _HEADING_SKEPTIC.search(text)
    raw_m = _HEADING_RAW.search(text)

    if syn_m:
        syn_start = syn_m.end()
        syn_end = sk_m.start() if sk_m else (raw_m.start() if raw_m else len(text))
        synthesis_block = text[syn_start:syn_end]
        out["synthesis_md"] = synthesis_block.strip()

        fc_start, fc_end = _find_section(synthesis_block, _HEADING_FILE_COVERAGE)
        if fc_start >= 0:
            out["file_coverage_md"] = synthesis_block[fc_start:fc_end].strip()

        con_start, con_end = _find_section(synthesis_block, _HEADING_CONSENSUS)
        if con_start >= 0:
            out["consensus_md"] = synthesis_block[con_start:con_end].strip()

        uni_start, uni_end = _find_section(synthesis_block, _HEADING_UNIQUE)
        if uni_start >= 0:
            out["unique_md"] = synthesis_block[uni_start:uni_end].strip()

        pri_start, pri_end = _find_section(synthesis_block, _HEADING_PRIORITY)
        if pri_start >= 0:
            out["priority_md"] = synthesis_block[pri_start:pri_end].strip()

    if sk_m:
        sk_start = sk_m.end()
        sk_end = raw_m.start() if raw_m else len(text)
        out["skeptic_md"] = text[sk_start:sk_end].strip()

    if raw_m:
        out["raw_reviews_md"] = text[raw_m.end() :].strip()

    return out


def _parse_markdown_table(section: str) -> list[list[str]]:
    """Parse a pipe table into rows of cell strings (skips separator row)."""
    rows: list[list[str]] = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r"^\|\s*:?-{3,}", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and not all(re.match(r"^:?-+$", c) for c in cells):
            rows.append(cells)
    if rows and _looks_like_header(rows[0]):
        rows = rows[1:]
    return rows


def _looks_like_header(cells: list[str]) -> bool:
    joined = " ".join(cells).lower()
    return any(
        kw in joined
        for kw in ("severity", "file", "reviewer", "issue", "finding", "status")
    )


def _strip_md_bold(s: str) -> str:
    return re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", s).strip()


def _parse_file_coverage_table(section: str) -> list[dict[str, Any]]:
    rows = _parse_markdown_table(section)
    out: list[dict[str, Any]] = []
    for cells in rows:
        if len(cells) < 3:
            continue
        file_cell = _strip_md_bold(cells[0]).strip("`")
        status = cells[2]
        has_issues = "issue" in status.lower() and "clean" not in status.lower()
        out.append(
            {
                "file": file_cell,
                "reviewers": cells[1],
                "status": status,
                "has_issues": has_issues,
            }
        )
    return out


def _parse_consensus_table(section: str) -> list[dict[str, Any]]:
    rows = _parse_markdown_table(section)
    out: list[dict[str, Any]] = []
    for cells in rows:
        if len(cells) < 4:
            continue
        severity = _strip_md_bold(cells[0]).upper()
        issue = _strip_md_bold(cells[1])
        files = _strip_md_bold(cells[2]).strip("`")
        reviewers = cells[3]
        trace = cells[4] if len(cells) > 4 else ""
        out.append(
            {
                "severity": severity,
                "issue": issue,
                "files": files,
                "reviewers": reviewers,
                "trace": trace,
            }
        )
    return out


def _parse_unique_table(section: str) -> list[dict[str, Any]]:
    rows = _parse_markdown_table(section)
    out: list[dict[str, Any]] = []
    for cells in rows:
        if len(cells) < 3:
            continue
        out.append(
            {
                "reviewer": _strip_md_bold(cells[0]),
                "finding": _strip_md_bold(cells[1]),
                "significance": cells[2],
            }
        )
    return out


def _parse_priority_list(section: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in section.splitlines():
        m = re.match(
            r"^\s*(\d+)\.\s+(?:\*\*(.+?)\*\*|(.+?))(?:\s*\((\w+(?:/\w+)?)\))?\s*:?\s*(.*)$",
            line.strip(),
        )
        if not m:
            continue
        rank = int(m.group(1))
        title = (m.group(2) or m.group(3) or "").strip()
        severity = (m.group(4) or _guess_severity(title)).upper()
        rationale = (m.group(5) or "").strip()
        file_m = re.search(r"`([^`]+)`", title)
        out.append(
            {
                "rank": rank,
                "title": title,
                "severity": severity,
                "file": file_m.group(1) if file_m else "",
                "rationale": rationale,
            }
        )
    return out


def _guess_severity(title: str) -> str:
    upper = title.upper()
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        if sev in upper:
            return sev
    return "LOW"


def _parse_skeptic_verdicts(section: str) -> list[dict[str, Any]]:
    """Parse STANDS/DISPROVEN blocks from skeptic gate output."""
    out: list[dict[str, Any]] = []
    # Match **DISPROVEN: Title** or **STANDS: Title** headings.
    pattern = re.compile(
        r"\*\*(DISPROVEN|STANDS):\s*(.+?)\*\*\s*\n(.*?)(?=\n\*\*(?:DISPROVEN|STANDS):|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    for m in pattern.finditer(section):
        verdict = m.group(1).upper()
        title = m.group(2).strip()
        body = m.group(3).strip()
        reasoning_m = re.search(
            r"\*\*Reasoning:\*\*\s*(.+?)(?=\n\*|\n\*\*Verdict|\Z)",
            body,
            re.DOTALL,
        )
        reasoning = reasoning_m.group(1).strip() if reasoning_m else body[:500]
        out.append(
            {
                "title": title,
                "verdict": verdict,
                "reasoning": reasoning,
            }
        )
    return out


def _normalize_match_key(s: str) -> str:
    """Lowercase alphanumeric key for fuzzy matching finding titles."""
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _skeptic_verdict_for(
    label: str, skeptic_verdicts: list[dict[str, Any]]
) -> str | None:
    """Return STANDS, DISPROVEN, or None if no matching skeptic block."""
    key = _normalize_match_key(label)
    if not key:
        return None
    best: tuple[int, str] | None = None
    for sv in skeptic_verdicts:
        sv_key = _normalize_match_key(sv.get("title", ""))
        if not sv_key:
            continue
        # Substring overlap — handles 'Path Traversal via destination_id in file.py'
        if key in sv_key or sv_key in key:
            score = len(sv_key)
        else:
            key_tokens = set(key.split())
            sv_tokens = set(sv_key.split())
            overlap = len(key_tokens & sv_tokens)
            if overlap < 2:
                continue
            score = overlap
        if best is None or score > best[0]:
            best = (score, sv["verdict"].upper())
    return best[1] if best else None


def _build_action_items(
    consensus: list[dict[str, Any]],
    priority: list[dict[str, Any]],
    skeptic_verdicts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build action list and dismissed list per triage rules."""
    dismissed: list[dict[str, Any]] = []
    action_items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for item in consensus:
        label = f"{item['issue']} {item['files']}"
        key = _normalize_match_key(label)
        verdict = _skeptic_verdict_for(label, skeptic_verdicts)
        entry = {
            "source": "consensus",
            "severity": item["severity"],
            "title": item["issue"],
            "file": item["files"].strip("`"),
            "reviewers": item["reviewers"],
            "skeptic": verdict,
            "trace": item.get("trace", ""),
        }
        if verdict == "DISPROVEN":
            dismissed.append(entry)
            continue
        if key not in seen_keys:
            seen_keys.add(key)
            action_items.append(entry)

    for item in priority:
        label = item["title"]
        key = _normalize_match_key(label)
        if key in seen_keys:
            continue
        verdict = _skeptic_verdict_for(label, skeptic_verdicts)
        if verdict == "DISPROVEN":
            dismissed.append(
                {
                    "source": "priority",
                    "severity": item["severity"],
                    "title": item["title"],
                    "file": item.get("file", ""),
                    "rank": item["rank"],
                    "skeptic": verdict,
                }
            )
            continue
        seen_keys.add(key)
        action_items.append(
            {
                "source": "priority",
                "severity": item["severity"],
                "title": item["title"],
                "file": item.get("file", ""),
                "rank": item["rank"],
                "rationale": item.get("rationale", ""),
                "skeptic": verdict,
            }
        )

    def sort_key(it: dict[str, Any]) -> tuple[int, int, int]:
        stands_first = 0 if it.get("skeptic") == "STANDS" else 1
        sev = _SEVERITY_ORDER.get(it.get("severity", "LOW"), 9)
        rank = it.get("rank", 99)
        return (stands_first, sev, rank)

    action_items.sort(key=sort_key)
    return dismissed, action_items


def _build_summary(
    consensus: list[dict[str, Any]],
    file_coverage: list[dict[str, Any]],
    skeptic_verdicts: list[dict[str, Any]],
    action_items: list[dict[str, Any]],
) -> dict[str, Any]:
    high = sum(1 for c in consensus if c["severity"] in ("HIGH", "CRITICAL"))
    medium = sum(1 for c in consensus if c["severity"] == "MEDIUM")
    low = sum(1 for c in consensus if c["severity"] == "LOW")
    files_with_issues = sum(1 for f in file_coverage if f.get("has_issues"))
    files_clean = sum(1 for f in file_coverage if not f.get("has_issues"))
    stands = sum(1 for s in skeptic_verdicts if s["verdict"] == "STANDS")
    disproven = sum(1 for s in skeptic_verdicts if s["verdict"] == "DISPROVEN")

    needs_attention = any(
        it.get("severity") in ("HIGH", "CRITICAL")
        for it in action_items
        if it.get("source") == "consensus"
    )

    return {
        "consensus_count": len(consensus),
        "high": high,
        "medium": medium,
        "low": low,
        "files_with_issues": files_with_issues,
        "files_clean": files_clean,
        "skeptic_stands": stands,
        "skeptic_disproven": disproven,
        "needs_attention": needs_attention,
        "action_count": len(action_items),
    }
