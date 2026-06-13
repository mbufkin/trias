"""Review Council configuration — all paths, models, and defaults."""

import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG = {
    "paths": {
        "mailbox": "~/.trias",
        # Subdirs created automatically: tasks, status, results, archive, uploads
    },
    "ollama": {
        "url": "http://localhost:11434",
        "timeout_per_model": 240,
        "synthesis_timeout": 300,
    },
    "council": [
        {
            "model": "qwen3-coder-next:q4_K_M",
            "label": "MoE agentic — systems, security, correctness",
        },
        {
            "model": "qwen2.5-coder:32b",
            "label": "Dense 32B base — code correctness, logic, edge cases",
        },
        {
            "model": "qwen2.5-coder-opencode:latest",
            "label": "Dense 32B OpenCode — patterns, refactoring, testability",
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
        "focus": "security, correctness, design, maintainability",
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


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load config, falling back to defaults for missing keys."""
    config = dict(DEFAULT_CONFIG)  # shallow copy

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


def _deep_merge(base: dict, override: dict) -> None:
    """Merge override into base in-place (nested dicts merged, not replaced)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
