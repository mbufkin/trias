"""Passive scan modes — one mechanical check per invocation."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .scan_config import ScanConfig, load_scan_config


def _python(project: Path) -> str:
    venv = project / ".venv" / "bin" / "python"
    if venv.is_file():
        return str(venv)
    return sys.executable


def run_bandit(python: str, paths: list[Path]) -> tuple[int, str]:
    existing = [str(p) for p in paths if p.exists()]
    if not existing:
        return 0, "(skipped — no bandit paths found)"
    cmd = [python, "-m", "bandit", "-r", *existing, "-ll", "-q"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip() or "(no medium+ findings)"


def run_pip_audit(python: str, requirements: Path) -> tuple[int, str]:
    if not requirements.is_file():
        return 0, f"(skipped — no {requirements.name})"
    cmd = [python, "-m", "pip_audit", "-r", str(requirements)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip() or "(no known vulns)"


def run_smoke(python: str, smoke_script: Path, *, ssh: bool, extra_args: list[str]) -> tuple[int, str]:
    if not smoke_script.is_file():
        return 1, f"smoke script not found: {smoke_script}"
    cmd = [python, str(smoke_script), "--skip-local", *extra_args]
    if ssh:
        cmd.append("--ssh")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip() or "(smoke finished)"


def write_mode_report(
    out_path: Path,
    *,
    project: Path,
    mode: str,
    body_section: str,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = f"""# Trias scan — {mode} — {project.name}

**Date:** {now}
**Project:** `{project}`
**Mode:** `{mode}`

For live HTTP probes use **Peira** (separate tool).

{body_section}
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")


def _resolve_smoke(project: Path, smoke: Path | None, cfg: ScanConfig) -> Path | None:
    if smoke is not None:
        return smoke if smoke.is_absolute() else project / smoke
    if cfg.smoke:
        return project / cfg.smoke
    return None


def run_static(
    project: Path,
    *,
    bandit_paths: list[str] | None,
    report_path: Path | None,
) -> int:
    project = project.resolve()
    cfg = load_scan_config(project)
    paths = bandit_paths if bandit_paths is not None else cfg.bandit_paths
    python = _python(project)

    print(f"Trias scan static — {project}")
    print(f"Python: {python}\n")

    code, out = run_bandit(python, [project / p for p in paths])
    print(out[:8000] or "(empty)")

    if report_path:
        write_mode_report(
            report_path,
            project=project,
            mode="static",
            body_section=f"## Bandit (medium+)\n\n```\n{out}\n```",
        )
        print(f"\nReport: {report_path}")
    return code


def run_deps(
    project: Path,
    *,
    requirements_name: str | None,
    report_path: Path | None,
) -> int:
    project = project.resolve()
    cfg = load_scan_config(project)
    req_name = requirements_name or cfg.requirements
    python = _python(project)
    req = project / req_name

    print(f"Trias scan deps — {project}")
    print(f"Python: {python}\n")

    code, out = run_pip_audit(python, req)
    print(out[:8000] or "(empty)")

    if report_path:
        write_mode_report(
            report_path,
            project=project,
            mode="deps",
            body_section=f"## pip-audit ({req_name})\n\n```\n{out}\n```",
        )
        print(f"\nReport: {report_path}")
    return code


def run_deploy(
    project: Path,
    *,
    smoke_script: Path | None,
    ssh: bool | None,
    smoke_extra: list[str],
    report_path: Path | None,
) -> int:
    project = project.resolve()
    cfg = load_scan_config(project)
    smoke = _resolve_smoke(project, smoke_script, cfg)
    use_ssh = cfg.smoke_ssh if ssh is None else ssh

    if smoke is None:
        print(
            "error: deploy scan needs a smoke script — pass --smoke or set scan.deploy.smoke in .trias.yaml",
            file=sys.stderr,
        )
        return 2

    python = _python(project)
    print(f"Trias scan deploy — {project}")
    print(f"Python: {python}")
    print(f"Smoke: {smoke}\n")

    code, out = run_smoke(python, smoke.resolve(), ssh=use_ssh, extra_args=smoke_extra)
    print(out[:12000] or "(empty)")

    if report_path:
        write_mode_report(
            report_path,
            project=project,
            mode="deploy",
            body_section=f"## smoke (`{smoke.name}`)\n\n```\n{out}\n```",
        )
        print(f"\nReport: {report_path}")
    return code


def run_all(
    project: Path,
    *,
    bandit_paths: list[str] | None,
    requirements_name: str | None,
    smoke_script: Path | None,
    ssh: bool | None,
    smoke_extra: list[str],
    report_path: Path | None,
) -> int:
    """Run static + deps + deploy in sequence (explicit opt-in for CI/nightly)."""
    project = project.resolve()
    cfg = load_scan_config(project)
    python = _python(project)
    paths = bandit_paths if bandit_paths is not None else cfg.bandit_paths
    req_name = requirements_name or cfg.requirements
    smoke = _resolve_smoke(project, smoke_script, cfg)
    use_ssh = cfg.smoke_ssh if ssh is None else ssh

    print(f"Trias scan all — {project}")
    print(f"Python: {python}\n")

    bandit_code, bandit_out = run_bandit(python, [project / p for p in paths])
    print("=== static (Bandit) ===")
    print(bandit_out[:4000] or "(empty)\n")

    audit_code, audit_out = run_pip_audit(python, project / req_name)
    print("=== deps (pip-audit) ===")
    print(audit_out[:4000] or "(empty)\n")

    smoke_code, smoke_out = 0, "(skipped — no smoke script)"
    if smoke is not None:
        print("=== deploy (smoke) ===")
        smoke_code, smoke_out = run_smoke(
            python, smoke.resolve(), ssh=use_ssh, extra_args=smoke_extra
        )
        print(smoke_out[:8000] or "(empty)\n")
    else:
        print("=== deploy (smoke) ===")
        print("(skipped — pass --smoke or set scan.deploy.smoke in .trias.yaml)\n")

    if report_path:
        write_mode_report(
            report_path,
            project=project,
            mode="all",
            body_section=(
                f"## Bandit (medium+)\n\n```\n{bandit_out}\n```\n\n"
                f"## pip-audit ({req_name})\n\n```\n{audit_out}\n```\n\n"
                f"## smoke\n\n```\n{smoke_out}\n```"
            ),
        )
        print(f"Report: {report_path}")

    return max(bandit_code, audit_code, smoke_code)
