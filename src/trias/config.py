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
    # Trias uses llama.cpp (llama-server OpenAI API), not Ollama.
    "llamacpp": {
        "url": "http://localhost:8080/v1/chat/completions",
        "timeout": 600,
    },
    "council": [
        {
            "model": "gemma4-31b",
            "label": "Security — data flow, sinks, exploit chains",
        },
        {
            "model": "gemma4-31b",
            "label": "Correctness — logic, edges, seams & interfaces",
        },
        {
            "model": "gemma4-31b",
            "label": "Patterns — locality, leverage, maintainability",
        },
    ],
    "synthesis": {
        "model": "gemma4-31b",
        "num_predict": 3072,
        "temperature": 0.3,
    },
    "skeptic": {
        "enabled": True,
        "model": "gemma4-31b",
        "num_predict": 2048,
        "temperature": 0.2,
        "timeout": 600,
    },
    "review": {
        "mode": "council",
        # sequential = one file per council pass (default, avoids whitewashing).
        # batch = legacy all-files-in-one-prompt (only for small submissions).
        "file_strategy": "sequential",
        "max_file_chars": 12000,
        "synthesis_chars_per_file": 4000,
        "num_predict": 2048,
        "temperature": 0.3,
        "poll_interval": 15,
        "focus": "security, correctness, deep vs shallow modules, seams & interfaces, locality, leverage, maintainability",
    },
    "focused_roles": {
        "security": {
            "model": "gemma4-31b",
            "label": "Security Reviewer",
            "principles": ["data_flow_trace", "exploit_chain", "sink_classification", "input_verification"],
        },
        "architecture": {
            "model": "gemma4-31b",
            "label": "Architecture Reviewer",
            "principles": ["deep_vs_shallow", "seams_and_interfaces", "locality", "leverage"],
        },
        "correctness": {
            "model": "gemma4-31b",
            "label": "Correctness + Patterns Reviewer",
            "principles": ["logic_errors", "edge_cases", "refactoring_opportunities", "test_gaps"],
        },
    },
    "principles": {}
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


def _deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict with override merged into base. Pure — no mutation."""
    import copy
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load config, returning a fresh merge of defaults + user overrides."""
    if config_path is None:
        config_path = _find_config()

    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(_DEFAULT_CONFIG, user_config)
    else:
        import copy
        config = copy.deepcopy(_DEFAULT_CONFIG)

    # Expand paths
    mailbox = Path(os.path.expanduser(config["paths"]["mailbox"]))
    config["paths"]["mailbox"] = str(mailbox)
    config["paths"]["tasks"] = str(mailbox / "tasks")
    config["paths"]["status"] = str(mailbox / "status")
    config["paths"]["results"] = str(mailbox / "results")
    config["paths"]["archive"] = str(mailbox / "archive")
    config["paths"]["uploads"] = str(mailbox / "uploads")

    return config
