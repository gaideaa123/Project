"""Explicit, stable Playwright context settings for reproducible UI tests.

This module deliberately does not rewrite ``navigator.webdriver`` or spoof
Canvas/WebGL fingerprints. Those patches are brittle, easy to detect, and turn
a test helper into an access-control bypass.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


def build_context_options(
    *,
    locale: str = "tr-TR",
    timezone_id: str = "Europe/Istanbul",
    width: int = 1366,
    height: int = 768,
    color_scheme: str = "light",
    extra_http_headers: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Return internally consistent options for ``browser.new_context``."""

    if not locale or not timezone_id:
        raise ValueError("locale and timezone_id are required")
    if width < 320 or height < 240:
        raise ValueError("viewport is too small for a browser UI test")
    if color_scheme not in {"light", "dark", "no-preference"}:
        raise ValueError("unsupported color_scheme")

    options: Dict[str, Any] = {
        "locale": locale,
        "timezone_id": timezone_id,
        "viewport": {"width": width, "height": height},
        "screen": {"width": width, "height": height},
        "color_scheme": color_scheme,
    }
    if extra_http_headers:
        options["extra_http_headers"] = dict(extra_http_headers)
    return options


def apply_test_page_defaults(page: Any, *, timeout_ms: int = 10_000) -> None:
    """Apply page-level reliability defaults without fingerprint spoofing."""

    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")
    page.set_default_timeout(timeout_ms)
    page.set_default_navigation_timeout(timeout_ms * 3)
