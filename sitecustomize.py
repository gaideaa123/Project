"""Provider compatibility loaded automatically by Python.

The UI historically called xAI/Grok while users supplied GroqCloud keys. A
Groq key starts with gsk_ and must be sent to api.groq.com, never api.x.ai.
Only that exact mismatch is rewritten; TikTok and all other HTTP calls remain
untouched.
"""
from __future__ import annotations

from typing import Any

try:
    import requests
except Exception:  # requests may not be installed during unrelated tooling
    requests = None


if requests is not None and not getattr(requests, "_signaldesk_provider_patch", False):
    _original_post = requests.post

    def _provider_aware_post(url: str, *args: Any, **kwargs: Any):
        headers = dict(kwargs.get("headers") or {})
        authorization = str(headers.get("Authorization") or "")
        token = authorization.removeprefix("Bearer ").strip()

        if url.rstrip("/") == "https://api.x.ai/v1/chat/completions" and token.startswith("gsk_"):
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = dict(kwargs.get("json") or {})
            payload["model"] = "llama-3.3-70b-versatile"
            kwargs["json"] = payload

        return _original_post(url, *args, **kwargs)

    requests.post = _provider_aware_post
    requests._signaldesk_provider_patch = True
