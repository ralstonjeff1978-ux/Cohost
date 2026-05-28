"""
AI Bridge — Universal LLM caller for Cohost
============================================
Routes call_ai() to the configured provider. Supports dynamic model
switching via set_model() for the brain selector feature.

Conversation-aware: maintains turn history for multi-turn podcast sessions.

Usage:
    from core.ai_bridge import call_ai, set_model, list_models
    response = call_ai("What do you think about that?", history=turns)
    set_model("mistral:7b-instruct")  # switch brain on the fly
"""

import os
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional, List, Dict, Generator

import requests

from core.paths import load_config as _load_config

log = logging.getLogger("ai_bridge")


def _get_provider_cfg(config: dict) -> tuple[str, dict]:
    provider = config["provider"]
    cfg = config["providers"].get(provider)
    if cfg is None:
        raise ValueError(f"Provider '{provider}' not found in config.yaml")
    return provider, cfg


# ── Runtime model override (brain selector) ───────────────────────────────────

_active_model: Optional[str] = None


def set_model(model_name: str) -> str:
    """Switch the active Ollama model at runtime. Accepts any model identifier —
    curated `brain_selector.available` is a menu, not a hard whitelist, so new
    Ollama releases can be typed in directly without editing config.yaml."""
    global _active_model
    config = _load_config()
    available = [m["name"] for m in config.get("brain_selector", {}).get("available", [])]
    _active_model = model_name
    if available and model_name not in available:
        log.info("Brain switched to: %s (not in curated list — that's fine)", model_name)
        return (f"Brain switched to: {model_name}\n"
                f"  (Not in the curated list — assuming you know it's a valid "
                f"Ollama model. Use /brain with no argument to see the menu.)")
    log.info("Brain switched to: %s", model_name)
    return f"Brain switched to: {model_name}"


def get_active_model() -> str:
    """Return currently active model name."""
    global _active_model
    if _active_model:
        return _active_model
    config = _load_config()
    return config.get("brain_selector", {}).get("default") or \
           config["providers"].get("ollama", {}).get("model", "unknown")


def list_models() -> List[Dict[str, str]]:
    """
    Return the list of available models, grouped for the UI.

    Each entry has: name, label, source ('local'|'cloud').
    Local entries come from a live query of Ollama's /api/tags (whatever Hans
    has pulled). Cloud entries come from the curated brain_selector.available
    list in config.yaml, filtered to ':cloud' / cloud-only identifiers.
    """
    config = _load_config()
    curated = config.get("brain_selector", {}).get("available", [])

    # Curated cloud entries: keep ones tagged ':cloud' or that look hosted.
    cloud: List[Dict[str, str]] = []
    cloud_names: set = set()
    for m in curated:
        name = m.get("name", "")
        if ":cloud" in name or name.endswith("-cloud"):
            entry = {**m, "source": "cloud"}
            cloud.append(entry)
            cloud_names.add(name)

    # Live local models from Ollama's /api/tags
    local: List[Dict[str, str]] = []
    try:
        endpoint = (config.get("providers", {})
                    .get("ollama", {})
                    .get("endpoint", "http://localhost:11434"))
        resp = requests.get(endpoint.rstrip("/") + "/api/tags", timeout=3)
        resp.raise_for_status()
        tags = resp.json().get("models", [])
        # Build a lookup of curated labels by name so locally-pulled curated
        # models still show their nice descriptions.
        curated_by_name = {m["name"]: m.get("label", "") for m in curated}
        for tag in tags:
            name = tag.get("name") or tag.get("model")
            if not name or name in cloud_names:
                continue
            label = curated_by_name.get(name)
            if not label:
                size_gb = (tag.get("size", 0) or 0) / (1024 ** 3)
                label = f"Local model ({size_gb:.1f} GB)" if size_gb else "Local model"
            local.append({"name": name, "label": label, "source": "local"})
    except Exception as e:
        log.debug("Could not query local Ollama tags: %s", e)

    return local + cloud


def reset_model() -> None:
    """Reset to the default model from config."""
    global _active_model
    _active_model = None
    log.info("Brain reset to config default")


# ── Provider callers ──────────────────────────────────────────────────────────

def _call_ollama(prompt: str, cfg: dict, system: Optional[str] = None,
                 history: Optional[List[Dict]] = None) -> str:
    """
    Call Ollama. Supports conversation history for multi-turn sessions.
    history format: [{"role": "user"|"assistant", "content": "..."}]
    """
    global _active_model
    model = _active_model or cfg["model"]
    params = cfg.get("parameters", {})

    if history:
        url = cfg["endpoint"].rstrip("/") + "/api/chat"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        payload = {"model": model, "messages": messages, "stream": False, **params}
        resp = requests.post(url, json=payload, timeout=cfg.get("timeout", 120))
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    else:
        url = cfg["endpoint"].rstrip("/") + "/api/generate"
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        payload = {"model": model, "prompt": full_prompt, "stream": False, **params}
        resp = requests.post(url, json=payload, timeout=cfg.get("timeout", 120))
        resp.raise_for_status()
        return resp.json()["response"].strip()


def _call_openai(prompt: str, cfg: dict, system: Optional[str] = None,
                 history: Optional[List[Dict]] = None) -> str:
    api_key = os.environ.get(cfg["api_key_env"])
    if not api_key:
        raise EnvironmentError(f"Environment variable '{cfg['api_key_env']}' is not set.")
    url = cfg["endpoint"].rstrip("/") + "/chat/completions"
    params = cfg.get("parameters", {})
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})
    payload = {"model": cfg["model"], "messages": messages, **params}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    resp = requests.post(url, json=payload, headers=headers, timeout=cfg.get("timeout", 60))
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_anthropic(prompt: str, cfg: dict, system: Optional[str] = None,
                    history: Optional[List[Dict]] = None) -> str:
    api_key = os.environ.get(cfg["api_key_env"])
    if not api_key:
        raise EnvironmentError(f"Environment variable '{cfg['api_key_env']}' is not set.")
    url = cfg["endpoint"].rstrip("/") + "/messages"
    params = cfg.get("parameters", {})
    messages = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})
    payload = {"model": cfg["model"], "messages": messages, **params}
    if system:
        payload["system"] = system
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=cfg.get("timeout", 60))
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()


_CALLERS = {
    "ollama":    _call_ollama,
    "openai":    _call_openai,
    "anthropic": _call_anthropic,
}

# ── Sentence splitter ─────────────────────────────────────────────────────────

_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')

def _split_sentences(text: str) -> List[str]:
    """Split text into speakable sentence chunks."""
    parts = _SENTENCE_END.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


# ── Streaming API (Ollama only) ───────────────────────────────────────────────

def stream_sentences(
    prompt: str,
    system: Optional[str] = None,
    history: Optional[List[Dict]] = None,
) -> Generator[str, None, None]:
    """
    Stream the LLM response and yield complete sentences as they form.
    Ollama only. Falls back to call_ai() for other providers.

    Yields one sentence at a time so TTS can start speaking immediately
    instead of waiting for the full response.
    """
    config = _load_config()
    provider, cfg = _get_provider_cfg(config)

    if provider != "ollama":
        # Non-streaming fallback: get full response, split into sentences
        full = call_ai(prompt, system=system, history=history)
        for s in _split_sentences(full):
            yield s
        return

    global _active_model
    model = _active_model or cfg["model"]
    url = cfg["endpoint"].rstrip("/") + "/api/chat"
    params = {k: v for k, v in cfg.get("parameters", {}).items()}
    params["temperature"] = params.get("temperature", 0.7)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    payload = {"model": model, "messages": messages, "stream": True, **params}

    log.info("[TIMING] llm_request_start model=%s history_turns=%d prompt_chars=%d",
             model, len(history) if history else 0, len(prompt))
    t_req = time.time()
    t_first_token = None
    t_first_sentence = None
    token_count = 0
    sentence_count = 0

    buffer = ""
    try:
        with requests.post(url, json=payload, stream=True,
                           timeout=cfg.get("timeout", 120)) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                try:
                    chunk = json.loads(raw_line)
                except Exception:
                    continue
                token = chunk.get("message", {}).get("content", "")
                if token and t_first_token is None:
                    t_first_token = time.time()
                    log.info("[TIMING] llm_ttft=%.2fs", t_first_token - t_req)
                buffer += token
                if token:
                    token_count += 1
                # Yield whenever we have a complete sentence
                while True:
                    m = _SENTENCE_END.search(buffer)
                    if not m:
                        break
                    sentence = buffer[:m.start() + 1].strip()
                    buffer = buffer[m.end():]
                    if sentence:
                        sentence_count += 1
                        if t_first_sentence is None:
                            t_first_sentence = time.time()
                            log.info("[TIMING] llm_first_sentence=%.2fs (ttft+%.2fs)",
                                     t_first_sentence - t_req,
                                     t_first_sentence - (t_first_token or t_req))
                        yield sentence
                if chunk.get("done"):
                    break
    except Exception as e:
        log.error("[TIMING] llm_stream_error after %.2fs: %s",
                  time.time() - t_req, e)

    # Yield any remaining text
    remainder = buffer.strip()
    if remainder:
        if t_first_sentence is None:
            t_first_sentence = time.time()
            log.info("[TIMING] llm_first_sentence=%.2fs (from remainder)",
                     t_first_sentence - t_req)
        sentence_count += 1
        yield remainder

    log.info("[TIMING] llm_total=%.2fs ttft=%.2fs tokens=%d sentences=%d",
             time.time() - t_req,
             (t_first_token - t_req) if t_first_token else -1,
             token_count, sentence_count)


# ── Public API ─────────────────────────────────────────────────────────────────

def call_ai(
    prompt: str,
    system: Optional[str] = None,
    history: Optional[List[Dict]] = None,
) -> str:
    """
    Send a prompt to the configured LLM provider.

    Args:
        prompt:  The user message / query.
        system:  Optional system prompt (persona, instructions).
        history: Optional conversation history list for multi-turn sessions.
                 Format: [{"role": "user"|"assistant", "content": "..."}]

    Returns:
        The model's response as a plain string.
    """
    config = _load_config()
    provider, cfg = _get_provider_cfg(config)
    caller = _CALLERS.get(provider)
    if caller is None:
        raise ValueError(f"No caller for provider '{provider}'. Valid: {list(_CALLERS)}")

    log.debug("[ai_bridge] provider=%s model=%s", provider, cfg.get("model"))
    return caller(prompt, cfg, system=system, history=history)


# ── CLI smoke test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "say hello in one sentence"
    if cmd == "--models":
        for m in list_models():
            print(f"  {m['name']:40s} {m['label']}")
        sys.exit(0)
    print(f"Active model: {get_active_model()}")
    print(f"Sending: {cmd!r}\n")
    try:
        print(call_ai(cmd))
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
