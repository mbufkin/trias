"""Load per-project scan settings from `.trias.yaml` (optional)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_BANDIT_PATHS = ["app", "scripts"]
DEFAULT_REQUIREMENTS = "requirements.txt"


@dataclass
class ScanConfig:
    bandit_paths: list[str] = field(default_factory=lambda: list(DEFAULT_BANDIT_PATHS))
    requirements: str = DEFAULT_REQUIREMENTS
    smoke: str | None = None
    smoke_ssh: bool = False


def _scan_block(raw: dict[str, Any]) -> dict[str, Any]:
    block = raw.get("scan")
    return block if isinstance(block, dict) else {}


def load_scan_config(project: Path) -> ScanConfig:
    """Merge defaults with optional `{project}/.trias.yaml` scan section."""
    cfg = ScanConfig()
    path = project / ".trias.yaml"
    if not path.is_file():
        return cfg

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SystemExit(f"invalid .trias.yaml in {project}: {exc}") from exc

    scan = _scan_block(raw if isinstance(raw, dict) else {})

    static = scan.get("static") or {}
    if isinstance(static, dict) and static.get("paths"):
        cfg.bandit_paths = [str(p) for p in static["paths"]]

    deps = scan.get("deps") or {}
    if isinstance(deps, dict) and deps.get("requirements"):
        cfg.requirements = str(deps["requirements"])

    deploy = scan.get("deploy") or {}
    if isinstance(deploy, dict):
        if deploy.get("smoke"):
            cfg.smoke = str(deploy["smoke"])
        if deploy.get("smoke_ssh"):
            cfg.smoke_ssh = bool(deploy["smoke_ssh"])

    return cfg
