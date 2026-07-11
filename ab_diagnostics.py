from __future__ import annotations

"""Local A/B evidence for phone versus web publication outcomes."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_data_dir

DATA_DIR = Path(user_data_dir("signaldesk-diagnostics", "SignalDesk"))
FILE = DATA_DIR / "phone-web-ab.json"
UTC = timezone.utc


@dataclass(frozen=True)
class ABResult:
    profile: str
    channel: str
    views_after_24h: int
    public: bool
    fyf_eligible: bool
    recorded_at: str


def record(profile: str, channel: str, views: int, public: bool, fyf: bool) -> ABResult:
    if channel not in {"phone", "web"}:
        raise ValueError("Kanal phone veya web olmalı")
    if views < 0:
        raise ValueError("İzlenme negatif olamaz")
    result = ABResult(profile.strip(), channel, int(views), bool(public), bool(fyf),
                      datetime.now(UTC).isoformat())
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        rows = json.loads(FILE.read_text(encoding="utf-8"))
        if not isinstance(rows, list): rows = []
    except (OSError, json.JSONDecodeError):
        rows = []
    rows.append(asdict(result))
    temporary = FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(rows[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(FILE)
    return result


def summary(profile: str) -> str:
    try:
        rows = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "Henüz A/B sonucu yok"
    matches = [row for row in rows if row.get("profile") == profile]
    if not matches:
        return "Henüz A/B sonucu yok"
    groups = {}
    for channel in ("phone", "web"):
        values = [int(row.get("views_after_24h", 0)) for row in matches if row.get("channel") == channel]
        if values: groups[channel] = round(sum(values) / len(values))
    if set(groups) == {"phone", "web"}:
        return f"24s ortalama: telefon {groups['phone']}, web {groups['web']}"
    return ", ".join(f"{key}: {value}" for key, value in groups.items()) or "Henüz A/B sonucu yok"
