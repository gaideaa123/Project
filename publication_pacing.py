from __future__ import annotations

"""Adaptive cooldown and canary control without random human simulation."""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_data_dir

DATA_DIR = Path(user_data_dir("signaldesk-studio", "SignalDesk"))
SETTINGS = DATA_DIR / "publication-pacing.json"
STATE = DATA_DIR / "publication-cooldown.json"
_LOCK = threading.RLock()
_LAST_COMPLETED = 0.0
DEFAULT_SECONDS = 90
TRANSIENT_MAX_RETRIES = 2


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


def _state() -> dict:
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE)


def classify(error: Exception) -> str:
    text = str(error).casefold()
    if any(term in text for term in ("timeout", "connection", "proxy", "503", "429", "temporar")):
        return "transient"
    if any(term in text for term in ("login", "session", "captcha", "doğrulama")):
        return "verification"
    if any(term in text for term in ("private", "restricted", "copyright", "telif", "eligible", "uygun")):
        return "policy"
    return "hard"


def register_failure(profile: str, error: Exception) -> int:
    category = classify(error)
    data = _state()
    row = data.get(profile, {"failures": 0})
    row["failures"] = int(row.get("failures", 0)) + 1
    base = get_seconds()
    multiplier = {"transient": 2, "verification": 8, "policy": 24, "hard": 6}[category]
    row.update(category=category, cooldown_until=time.time() + min(86400, base * multiplier * row["failures"]),
               updated_at=datetime.now(timezone.utc).isoformat())
    data[profile] = row
    _write(data)
    return int(row["cooldown_until"])


def register_success(profile: str) -> None:
    data = _state()
    data[profile] = {"failures": 0, "category": "ok", "cooldown_until": 0,
                     "updated_at": datetime.now(timezone.utc).isoformat()}
    _write(data)


def wait_before(profile: str, status=None) -> None:
    row = _state().get(profile, {})
    cooldown = max(0.0, float(row.get("cooldown_until", 0)) - time.time())
    with _LOCK:
        spacing = max(0.0, get_seconds() - (time.monotonic() - _LAST_COMPLETED))
    remaining = max(cooldown, spacing)
    while remaining > 0:
        if status: status(f"{profile}: risk cooldown {int(remaining) + 1} sn")
        sleep_for = min(5.0, remaining)
        time.sleep(sleep_for)
        remaining -= sleep_for


def should_retry(error: Exception, attempt: int) -> bool:
    return classify(error) == "transient" and attempt < TRANSIENT_MAX_RETRIES


def retry_delay(attempt: int) -> int:
    return min(60, 5 * (2 ** attempt))


def mark_completed(profile: str = "") -> None:
    global _LAST_COMPLETED
    with _LOCK: _LAST_COMPLETED = time.monotonic()
    if profile: register_success(profile)
