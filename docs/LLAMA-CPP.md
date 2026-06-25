# llama.cpp backend

Trias **only** talks to [llama.cpp](https://github.com/ggerganov/llama.cpp) via
`llama-server`'s **OpenAI-compatible API** (`/v1/chat/completions`). Ollama is
not used.

---

## Why llama.cpp

On GB10 (Lenovo PGX), inference runs through CUDA `llama-server` with tuned KV
cache, context, and jinja templates — the same path as Gemma council and other
GB10 workflows.

---

## Quick start (GB10)

```bash
# 1. Start a model server (systemd user unit)
systemctl --user start llama-cuda@gemma4-31b

# 2. Confirm API
curl -s http://127.0.0.1:8080/v1/models | head

# 3. Config — copy example and set model id from /v1/models
cp ~/tools/trias/config.example.yaml ~/.trias/config.yaml

# 4. Worker + submit
trias worker &
trias submit --wait --focus security app/security.py
```

---

## Configuration

```yaml
llamacpp:
  url: http://localhost:8080/v1/chat/completions
  timeout: 600

council:
  - model: /home/lenovo/llama.cpp/models/gemma4-31b.gguf   # from /v1/models
    label: Security lens

synthesis:
  model: /home/lenovo/llama.cpp/models/gemma4-31b.gguf

skeptic:
  enabled: true
  model: /home/lenovo/llama.cpp/models/gemma4-31b.gguf
  timeout: 600
```

**`model`** must match an id from `GET /v1/models` (often the full GGUF path).

**`url`** on a council row overrides the global `llamacpp.url` for that role.

---

## Multiple models

One `llama-server` loads **one** GGUF. Use per-role `url` for different ports,
or the same model with different reviewer labels (default on GB10).

---

## Migrating from Ollama

Remove `ollama:` and `llamacpp: true` flags. Use `config.example.yaml`.
