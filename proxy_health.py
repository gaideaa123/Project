from __future__ import annotations

"""Proxy availability, stability, latency and region checks.

Tests use ordinary HTTPS requests through the configured proxy. Credentials are
never logged or written to reports. No reputation bypass or IP rotation occurs.
"""

import hashlib
import json
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from platformdirs import user_data_dir

UTC = timezone.utc
DATA_DIR = Path(user_data_dir("signaldesk-profile-network", "SignalDesk"))
HEALTH_FILE = DATA_DIR / "proxy-health.json"
IP_URL = "https://api.ipify.org?format=json"
GEO_URL = "https://ipapi.co/json/"
MAX_AGE = timedelta(hours=24)
MAX_MEDIAN_LATENCY_MS = 5000


class ProxyHealthError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProxyHealth:
    fingerprint: str
    ok: bool
    exit_ip: str
    country_code: str
    median_latency_ms: int
    checked_at: str
    detail: str = ""


def fingerprint(identity) -> str:
    value = f"{identity.server}|{identity.username}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _proxy_url(identity) -> str:
    parsed = urlparse(identity.server)
    auth = ""
    if identity.username:
        auth = f"{quote(identity.username, safe='')}:{quote(identity.password, safe='')}@"
    return f"{parsed.scheme}://{auth}{parsed.hostname}:{parsed.port}"


def _proxies(identity) -> dict[str, str]:
    value = _proxy_url(identity)
    return {"http": value, "https": value}


def _direct_ip(timeout: int = 8) -> str:
    try:
        response = requests.get(IP_URL, timeout=timeout)
        response.raise_for_status()
        return str(response.json().get("ip") or "")
    except Exception:
        return ""


def test(identity, attempts: int = 3, timeout: int = 15) -> ProxyHealth:
    identity.validate()
    if not identity.server:
        raise ProxyHealthError("Doğrudan bağlantı proxy testiyle kullanılamaz")
    exits: list[str] = []
    latencies: list[int] = []
    proxy_map = _proxies(identity)
    direct_ip = _direct_ip()
    try:
        for _ in range(attempts):
            started = time.perf_counter()
            response = requests.get(IP_URL, proxies=proxy_map, timeout=timeout)
            response.raise_for_status()
            latency = round((time.perf_counter() - started) * 1000)
            exit_ip = str(response.json().get("ip") or "").strip()
            if not exit_ip:
                raise ProxyHealthError("Proxy çıkış IP'si okunamadı")
            exits.append(exit_ip)
            latencies.append(latency)
        if len(set(exits)) != 1:
            raise ProxyHealthError("Proxy art arda testlerde IP değiştirdi; sabit değil")
        if direct_ip and exits[0] == direct_ip:
            raise ProxyHealthError("Proxy çıkış IP'si doğrudan bağlantıyla aynı; yönlendirme doğrulanamadı")
        geo = requests.get(GEO_URL, proxies=proxy_map, timeout=timeout)
        geo.raise_for_status()
        country = str(geo.json().get("country_code") or "").upper()
        median = round(statistics.median(latencies))
        if median > MAX_MEDIAN_LATENCY_MS:
            raise ProxyHealthError(f"Proxy çok yavaş: medyan {median} ms")
        result = ProxyHealth(
            fingerprint(identity), True, exits[0], country, median,
            datetime.now(UTC).isoformat(), "HTTPS ve sabit çıkış IP doğrulandı",
        )
    except Exception as exc:
        result = ProxyHealth(
            fingerprint(identity), False, exits[-1] if exits else "", "",
            round(statistics.median(latencies)) if latencies else 0,
            datetime.now(UTC).isoformat(), str(exc),
        )
    record(result)
    return result


def _load() -> dict[str, dict]:
    try:
        data = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def record(result: ProxyHealth) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = _load()
    data[result.fingerprint] = asdict(result)
    temporary = HEALTH_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(HEALTH_FILE)


def latest(identity) -> ProxyHealth | None:
    row = _load().get(fingerprint(identity))
    try:
        return ProxyHealth(**row) if row else None
    except TypeError:
        return None


def require_healthy(identity) -> ProxyHealth:
    result = latest(identity)
    if result is None:
        raise ProxyHealthError("Bu proxy test edilmedi. Proxy Test sekmesinden test edin.")
    try:
        checked = datetime.fromisoformat(result.checked_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProxyHealthError("Proxy test kaydı bozuk; yeniden test edin") from exc
    if datetime.now(UTC) - checked > MAX_AGE:
        raise ProxyHealthError("Proxy testi 24 saatten eski; yeniden test edin")
    if not result.ok:
        raise ProxyHealthError(f"Proxy sağlık testi başarısız: {result.detail}")
    return result
