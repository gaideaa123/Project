"""Azure transport and Qt compatibility loaded automatically by Python."""
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


def _azure_text(value: str) -> str:
    replacements = (
        ("Profiller + Grok", "Profiller + Azure GPT-4o"),
        ("Grok caption rehberi", "Azure GPT-4o caption rehberi"),
        ("Grok API Key", "Azure GPT-4o API Key"),
        ("Grok API", "Azure GPT-4o API"),
        ("Grok caption", "Azure GPT-4o caption"),
        ("GROK CAPTION", "AZURE GPT-4O CAPTION"),
        ("Grok", "Azure GPT-4o"),
        ("grok", "Azure GPT-4o"),
    )
    for old, new in replacements:
        value = value.replace(old, new)
    return value


try:
    from PySide6.QtWidgets import QLabel, QPushButton, QTabWidget

    _label_init = QLabel.__init__
    _button_init = QPushButton.__init__
    _insert_tab = QTabWidget.insertTab
    _add_tab = QTabWidget.addTab

    def _label_azure(self, *args, **kwargs):
        args = list(args)
        if args and isinstance(args[0], str):
            args[0] = _azure_text(args[0])
        _label_init(self, *args, **kwargs)

    def _button_azure(self, *args, **kwargs):
        args = list(args)
        if args and isinstance(args[0], str):
            args[0] = _azure_text(args[0])
        _button_init(self, *args, **kwargs)

    def _insert_tab_azure(self, index, widget, label):
        return _insert_tab(self, index, widget, _azure_text(label))

    def _add_tab_azure(self, widget, label):
        return _add_tab(self, widget, _azure_text(label))

    QLabel.__init__ = _label_azure
    QPushButton.__init__ = _button_azure
    QTabWidget.insertTab = _insert_tab_azure
    QTabWidget.addTab = _add_tab_azure
except Exception:
    pass


# app_tr supports multiple generations of app.py. Older processing panels use
# QVBoxLayout.insertLayout, while newer panels use QGridLayout. Give the grid
# the same narrow compatibility operation so startup never depends on layout
# implementation details.
try:
    from PySide6.QtWidgets import QGridLayout

    if not hasattr(QGridLayout, "insertLayout"):
        def _grid_insert_layout(self, _index, layout, _stretch=0):
            row = self.rowCount()
            columns = max(1, self.columnCount())
            self.addLayout(layout, row, 0, 1, columns)

        QGridLayout.insertLayout = _grid_insert_layout
except Exception:
    pass
