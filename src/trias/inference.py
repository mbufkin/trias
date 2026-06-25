"""Trias inference — llama.cpp server only (OpenAI-compatible API).

Trias talks to a local llama-server (`/v1/chat/completions`), not Ollama.
One server typically loads one GGUF; point optional per-role `url` at different ports.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("trias")


def validate_model(model: str) -> bool:
    """Model id or GGUF path — allow slashes for llama.cpp model paths."""
    import re
    return bool(re.fullmatch(r"[a-zA-Z0-9._:/\\-]{1,256}", model))


def resolve_chat_url(config: dict[str, Any], override: str | None = None) -> str:
    if override:
        return override
    llc = config.get("llamacpp") or {}
    return llc.get("url", "http://localhost:8080/v1/chat/completions")


def models_url(chat_url: str) -> str:
    """Derive /v1/models from a chat/completions URL."""
    if chat_url.rstrip("/").endswith("/v1/chat/completions"):
        return chat_url.rsplit("/v1/chat/completions", 1)[0] + "/v1/models"
    base = chat_url.rstrip("/").rsplit("/", 1)[0]
    return f"{base}/v1/models"


def llama_cpp_generate(
    config: dict[str, Any],
    model: str,
    prompt: str,
    *,
    url: str | None = None,
    timeout: int = 600,
    num_predict: int = 2048,
    temperature: float = 0.3,
) -> str:
    """Call llama.cpp server (OpenAI-compatible chat completions)."""
    if not validate_model(model):
        raise RuntimeError(f"invalid model name: {model!r}")

    llc = config.get("llamacpp") or {}
    chat_url = resolve_chat_url(config, url)
    api_key = llc.get("api_key")

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": num_predict,
        "temperature": temperature,
        "stream": False,
    }).encode()

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(chat_url, data=payload, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        raise RuntimeError(f"llama.cpp HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach llama.cpp at {chat_url}: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError("llama.cpp returned non-JSON response") from e

    if "error" in data:
        raise RuntimeError(f"llama.cpp error: {data['error']}")
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("llama.cpp returned empty choices")
    content = choices[0].get("message", {}).get("content", "")
    if not content or not str(content).strip():
        raise RuntimeError("llama.cpp returned empty content")
    return str(content)


def check_llamacpp_health(
    config: dict[str, Any],
    *,
    url: str | None = None,
    model: str | None = None,
    timeout: int = 30,
    retries: int = 3,
) -> bool:
    """Ping llama.cpp — list models, optionally verify model id is advertised."""
    import time

    chat_url = resolve_chat_url(config, url)
    list_url = (config.get("llamacpp") or {}).get("models_url") or models_url(chat_url)

    for attempt in range(retries):
        try:
            req = urllib.request.Request(list_url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            ids: set[str] = set()
            for entry in data.get("data", data.get("models", [])):
                if isinstance(entry, dict):
                    for key in ("id", "model", "name"):
                        if entry.get(key):
                            ids.add(str(entry[key]))
            if model and ids:
                if model in ids:
                    return True
                # llama.cpp often exposes full GGUF path — match basename
                if any(model in i or i.endswith(model) for i in ids):
                    return True
                logger.warning(
                    "llama.cpp up at %s but model %r not in %d advertised ids",
                    list_url, model, len(ids),
                )
                return True  # server up; model field may still work
            return True
        except Exception as e:
            if attempt < retries - 1:
                delay = 0.5 * (2 ** attempt)
                logger.debug("llama.cpp health retry %s: %s", attempt + 1, e)
                time.sleep(delay)
            else:
                logger.warning("llama.cpp health failed for %s: %s", list_url, e)
    return False
