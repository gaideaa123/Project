"""Route the caption request to Azure GPT-4o.

Loaded automatically by Python. Secrets are supplied through the UI/keyring and
are never stored in this file.
"""
from __future__ import annotations

import os
from typing import Any

try:
    import requests
except Exception:
    requests = None

AZURE_DEFAULT_URL = (
    "https://yedekhesap145566-4746-resource.cognitiveservices.azure.com/"
    "openai/deployments/gpt-4o/chat/completions?api-version=2025-01-01-preview"
)

if requests is not None and not getattr(requests, "_signaldesk_azure_patch", False):
    _original_post = requests.post

    def _azure_caption_post(url: str, *args: Any, **kwargs: Any):
        if url.rstrip("/") in {
            "https://api.x.ai/v1/chat/completions",
            "https://api.groq.com/openai/v1/chat/completions",
        }:
            headers = dict(kwargs.get("headers") or {})
            authorization = str(headers.pop("Authorization", ""))
            key = authorization.removeprefix("Bearer ").strip()
            if not key:
                raise RuntimeError("Azure GPT-4o API anahtarı boş")

            azure_url = os.getenv("AZURE_GPT4O_API_URL", AZURE_DEFAULT_URL).strip()
            if not azure_url.startswith("https://") or "/chat/completions" not in azure_url:
                raise RuntimeError("Azure GPT-4o API URL geçersiz")

            headers["api-key"] = key
            headers["Content-Type"] = "application/json"
            payload = dict(kwargs.get("json") or {})
            payload.pop("model", None)
            kwargs["headers"] = headers
            kwargs["json"] = payload
            url = azure_url

        return _original_post(url, *args, **kwargs)

    requests.post = _azure_caption_post
    requests._signaldesk_azure_patch = True
