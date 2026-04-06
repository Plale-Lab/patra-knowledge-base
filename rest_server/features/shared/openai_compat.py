from __future__ import annotations

from typing import Any

import httpx


def _is_litellm_tapis_host(api_base: str) -> bool:
    lowered = (api_base or "").lower()
    return "litellm.pods.tacc.tapis.io" in lowered


def build_chat_completions_url(api_base: str) -> str:
    base = (api_base or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def build_models_url(api_base: str) -> str:
    base = (api_base or "").rstrip("/")
    if base.endswith("/models"):
        return base
    if _is_litellm_tapis_host(base):
        litellm_base = base.removesuffix("/v1")
        return f"{litellm_base}/models"
    if base.endswith("/v1"):
        return f"{base}/models"
    return f"{base}/v1/models"


def extract_message_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts: list[str] = []
        for item in message:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if isinstance(text, str) and text:
                    parts.append(text)
        return "\n".join(parts).strip()
    if isinstance(message, dict):
        text = message.get("text") or message.get("content") or ""
        return text if isinstance(text, str) else ""
    return ""


def is_generation_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(token in lowered for token in ("embed", "embedding", "rerank", "moderation", "whisper", "tts"))


def model_priority(model_id: str) -> tuple[int, str]:
    lowered = model_id.lower()
    if "gemma" in lowered:
        return (0, lowered)
    if "llama" in lowered:
        return (1, lowered)
    if "qwen" in lowered:
        return (2, lowered)
    if "glm" in lowered:
        return (3, lowered)
    return (4, lowered)


def list_available_models(
    *,
    api_base: str,
    api_key: str | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout_seconds: int = 10,
) -> list[str]:
    headers: dict[str, str] = dict(extra_headers or {})
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.get(build_models_url(api_base), headers=headers)
        response.raise_for_status()
        payload = response.json()
    models: list[str] = []
    for item in payload.get("data", []):
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id.strip() and is_generation_model(model_id):
            models.append(model_id.strip())
    return sorted(dict.fromkeys(models), key=model_priority)


def chat_text(
    *,
    api_base: str,
    model: str,
    messages: list[dict[str, str]],
    api_key: str | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout_seconds: int = 60,
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> tuple[str, str]:
    headers = {"Content-Type": "application/json", **(extra_headers or {})}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(build_chat_completions_url(api_base), headers=headers, json=payload)
        response.raise_for_status()
        parsed = response.json()
    message = parsed["choices"][0]["message"]
    content = extract_message_text(message.get("content"))
    if content:
        return content.strip(), model
    reasoning = extract_message_text(message.get("reasoning_content"))
    if reasoning:
        return reasoning.strip(), model
    raise ValueError("Model did not return text content")


def chat_text_with_model_fallback(
    *,
    api_base: str,
    model: str | None,
    messages: list[dict[str, str]],
    api_key: str | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout_seconds: int = 60,
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> tuple[str, str]:
    candidates = [model] if model else list_available_models(
        api_base=api_base,
        api_key=api_key,
        extra_headers=extra_headers,
        timeout_seconds=min(10, timeout_seconds),
    )
    attempted: list[str] = []
    last_error: Exception | None = None
    for candidate in candidates:
        if not candidate:
            continue
        attempted.append(candidate)
        try:
            return chat_text(
                api_base=api_base,
                model=candidate,
                messages=messages,
                api_key=api_key,
                extra_headers=extra_headers,
                timeout_seconds=timeout_seconds,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    attempted_label = ", ".join(attempted) or "(none)"
    if last_error:
        raise RuntimeError(f"All text-generation models failed. attempted_models=[{attempted_label}] last_error={last_error}") from last_error
    raise RuntimeError("No text-generation models available")
