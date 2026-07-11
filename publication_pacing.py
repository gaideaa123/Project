from __future__ import annotations

"""Deterministic, respectful delay between sequential account publications."""

import json
import threading
import time
from pathlib import Path

from platformdirs import user_data_dir

DATA_DIR = Path(user_data_dir("signaldesk-studio", "SignalDesk"))
SETTINGS = DATA_DIR / "publication-pacing.json"
_LOCK = threading.RLock()
_LAST_COMPLETED = 0.0
DEFAULT_SECONDS = 90


def get_seconds() -> int:
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return max(30, min(900, int(data.get("seconds", DEFAULT_SECONDS))))
    except Exception:
        return DEFAULT_SECONDS


def set_seconds(value: int) -> None:
    seconds = max(30, min(900, int(value)))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS.with_suffix(".tmp")
    temporary.write_text(json.dumps({"seconds": seconds}, indent=2), encoding="utf-8")
    temporary.replace(SETTINGS)


def wait_before(profile: str, status=None) -> None:
    with _LOCK:
        remaining = get_seconds() - (time.monotonic() - _LAST_COMPLETED)
    while remaining > 0:
        if status:
            status(f"{profile}: önceki hesaptan sonra {int(remaining) + 1} sn güvenli bekleme")
        sleep_for = min(5.0, remaining)
        time.sleep(sleep_for)
        remaining -= sleep_for


def mark_completed() -> None:
    global _LAST_COMPLETED
    with _LOCK:
        _LAST_COMPLETED = time.monotonic()
