"""Review Council configuration — all paths, models, and defaults.

Configuration is loaded from a YAML file (or defaults). The defaults
are stored in a private module-level dict; all access goes through
load_config() which returns a deep-merged copy — no shared mutable state.
"""

import os
from pathlib import Path
from typing import Any

import yaml


# Private — never mutate. load_config() returns a deep-merged copy.
_DEFAULT_CONFIG: dict[str, Any] = {
    "paths": {
        "mailbox": "~/.trias",
    },
    "ollama": {
        "url": "http://localhost:11434",
        "timeout_per_model": 240,
        "synthesis_timeout": 300,
    },
    "council": [
        {
            "model": "qwen3-coder-next:q4_K_M",
            "label": "MoE agentic — systems, security, deep module analysis",
        },
        {
            "model": "qwen2.5-coder:32b",
            "label": "Dense 32B base — correctness, logic, seams & interfaces",
        },
        {
            "model": "qwen2.5-coder-opencode:latest",
            "label": "Dense 32B OpenCode — patterns, locality, refactoring",
        },
    ],
    "synthesis": {
        "model": "qwen3-coder-next:q4_K_M",
        "num_predict": 1536,
        "temperature": 0.3,
    },
    "review": {
        "max_file_chars": 5000,
        "num_predict": 1536,
        "temperature": 0.3,
        "poll_interval": 15,
        "focus": "security, correctness, deep vs shallow modules, seams & interfaces, locality, leverage, maintainability",
    },
}


def _find_config() -> Path | None:
    """Search for config.yaml in standard locations."""
    candidates = [
        Path("config.yaml"),
        Path("trias.yaml"),
        Path.home() / ".config" / "trias" / "config.yaml",
        Path.home() / ".trias" / "config.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _deep_merge(base: dict, override: dict) -> None:
    """Merge override into base in-place. Nested dicts are merged, not replaced."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load config, merging user overrides onto a copy of the defaults.

    Returns a fresh dict every call — no shared mutable state.
    """
    import copy
    config = copy.deepcopy(_DEFAULT_CONFIG)

    if config_path is None:
        config_path = _find_config()

    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {}
        _deep_merge(config, user_config)

    # Expand paths
    mailbox = Path(os.path.expanduser(config["paths"]["mailbox"]))
    config["paths"]["mailbox"] = str(mailbox)
    config["paths"]["tasks"] = str(mailbox / "tasks")
    config["paths"]["status"] = str(mailbox / "status")
    config["paths"]["results"] = str(mailbox / "results")
    config["paths"]["archive"] = str(mailbox / "archive")
    config["paths"]["uploads"] = str(mailbox / "uploads")

    return config
