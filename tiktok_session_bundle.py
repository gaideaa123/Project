from __future__ import annotations

"""Parse and persist the minimal TikTok authentication cookie bundle."""

import json
import re
from collections.abc import Mapping

AUTH_COOKIE_NAMES = (
    "sessionid", "sessionid_ss", "sid_guard", "sid_tt", "uid_tt", "uid_tt_ss",
)


def _pairs(raw: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for part in raw.strip().split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name in AUTH_COOKIE_NAMES and value:
            rows[name] = value
    return rows


def parse(raw: str) -> dict[str, str]:
    """Accept a raw session value, Cookie header, or exported JSON cookie list."""
    value = raw.strip()
    if not value:
        raise ValueError("Session bilgisi boş")
    rows: dict[str, str] = {}
    if value.startswith("[") or value.startswith("{"):
        try:
            payload = json.loads(value)
            items = payload if isinstance(payload, list) else payload.get("cookies", [payload])
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                name = str(item.get("name") or "").strip()
                cookie_value = str(item.get("value") or "").strip()
                if name in AUTH_COOKIE_NAMES and cookie_value:
                    rows[name] = cookie_value
        except (ValueError, TypeError, json.JSONDecodeError):
            rows = {}
    if not rows:
        rows = _pairs(value)
    if not rows:
        if re.search(r"\s", value) or len(value) < 16:
            raise ValueError("Geçerli sessionid veya TikTok Cookie başlığı girin")
        rows = {"sessionid": value, "sessionid_ss": value}
    primary = rows.get("sessionid") or rows.get("sessionid_ss")
    if not primary or len(primary) < 16 or re.search(r"\s", primary):
        raise ValueError("Cookie paketinde geçerli sessionid/sessionid_ss yok")
    rows.setdefault("sessionid", primary)
    rows.setdefault("sessionid_ss", primary)
    return rows


def dumps(rows: Mapping[str, str]) -> str:
    clean = {name: str(rows[name]) for name in AUTH_COOKIE_NAMES if rows.get(name)}
    return json.dumps(clean, ensure_ascii=False, separators=(",", ":"))


def loads(raw: str) -> dict[str, str]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return {name: str(value) for name, value in payload.items() if name in AUTH_COOKIE_NAMES and value}
    except (ValueError, TypeError, json.JSONDecodeError):
        pass
    return parse(raw)
