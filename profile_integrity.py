from __future__ import annotations

"""Bind a profile to its long-lived browser, proxy, region and session identity."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_data_dir

DATA_DIR = Path(user_data_dir("signaldesk-profile-integrity", "SignalDesk"))
MANIFEST = DATA_DIR / "profiles.json"
UTC = timezone.utc


class ProfileIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProfileManifest:
    profile: str
    browser_dir: str
    proxy_fingerprint: str
    country_code: str
    session_fingerprint: str
    created_at: str
    last_verified_at: str


def secret_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _load() -> dict[str, dict]:
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(data: dict[str, dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = MANIFEST.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(MANIFEST)


def verify(profile: str, browser_dir: Path, proxy_fingerprint: str,
           country_code: str, session_value: str) -> ProfileManifest:
    key = profile.strip().casefold()
    if not key:
        raise ProfileIntegrityError("Profil adı boş")
    now = datetime.now(UTC).isoformat()
    session_fp = secret_fingerprint(session_value)
    current = ProfileManifest(
        profile, str(browser_dir.resolve()), proxy_fingerprint, country_code,
        session_fp, now, now,
    )
    data = _load()
    previous = data.get(key)
    if previous:
        checks = {
            "browser_dir": current.browser_dir,
            "proxy_fingerprint": current.proxy_fingerprint,
            "country_code": current.country_code,
        }
        for field, expected in checks.items():
            old = str(previous.get(field) or "")
            if old and expected and old != expected:
                raise ProfileIntegrityError(
                    f"{profile} profil bütünlüğü değişti ({field}). Profil/proxy kilidini "
                    "bilinçli olarak sıfırlamadan yayın durduruldu."
                )
        old_session = str(previous.get("session_fingerprint") or "")
        if old_session and session_fp and old_session != session_fp:
            raise ProfileIntegrityError(
                f"{profile} Session ID değişti. Yeni session ile devam etmeden önce profil "
                "bütünlüğünü açıkça sıfırlayın."
            )
        current = ProfileManifest(
            profile, current.browser_dir, current.proxy_fingerprint,
            current.country_code, session_fp or old_session,
            str(previous.get("created_at") or now), now,
        )
    data[key] = asdict(current)
    _write(data)
    return current


def reset(profile: str) -> None:
    data = _load()
    data.pop(profile.strip().casefold(), None)
    _write(data)
