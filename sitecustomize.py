"""SignalDesk startup compatibility module.

Kept intentionally side-effect free. Azure GPT is called explicitly by app_tr.py;
network clients and Qt constructors must never be monkey-patched process-wide.
"""

from __future__ import annotations


def azure_caption_transport_is_explicit() -> bool:
    """Compatibility probe used by smoke tests and older launch scripts."""
    return True
