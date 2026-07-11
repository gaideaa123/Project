from __future__ import annotations

"""Proxy connectivity verification with browser and TikTok target checks."""

import hashlib
import json
import statistics
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import requests
from platformdirs import user_data_dir

import network_identity
import socks_bridge

UTC = timezone.utc
DATA_DIR = Path(user_data_dir("signaldesk-profile-network", "SignalDesk"))
HEALTH_FILE = DATA_DIR / "proxy-health.json"
IP_ENDPOINTS = (
 ("https://api.ipify.org?format=json", "ip"),
 ("https://api64.ipify.org?format=json", "ip"),
 ("https://httpbin.org/ip", "origin"),
)
GEO_ENDPOINTS = ("https://ipapi.co/{ip}/json/", "https://ipwho.is/{ip}")
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
 asn: str = ""
 org: str = ""
 risk_flags: tuple[str, ...] = ()

def fingerprint(identity: network_identity.NetworkIdentity) -> str:
 return hashlib.sha256(f"{identity.server}|{identity.username}".encode()).hexdigest()

def _load() -> dict[str, Any]:
 try:
  data = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
  return data if isinstance(data, dict) else {}
 except Exception:
  return {}

def record(result: ProxyHealth) -> None:
 DATA_DIR.mkdir(parents=True, exist_ok=True)
 data = _load(); row = asdict(result); row["risk_flags"] = list(result.risk_flags); data[result.fingerprint] = row
 temporary = HEALTH_FILE.with_suffix(".tmp")
 temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
 temporary.replace(HEALTH_FILE)

def _session(proxies: dict[str, str] | None = None) -> requests.Session:
 session = requests.Session(); session.trust_env = False
 if proxies: session.proxies.update(proxies)
 session.headers.update({"User-Agent": "SignalDesk-ProxyCheck/2.0"})
 return session

@contextmanager
def _identity_session(identity: network_identity.NetworkIdentity) -> Iterator[requests.Session]:
 """Use the same local bridge as Chromium for SOCKS5, avoiding InvalidSchema."""
 bridge = None
 session = None
 try:
  if urlparse(identity.server).scheme.casefold() == "socks5":
   bridge = socks_bridge.AuthenticatedSocksBridge(identity).start()
   server = bridge.proxy["server"]
   proxies = {"http": server, "https": server}
  else:
   proxies = network_identity.requests_proxies(identity)
  session = _session(proxies)
  yield session
 finally:
  if session is not None:
   session.close()
  if bridge is not None:
   bridge.close()

def _extract_ip(payload: dict[str, Any], field: str) -> str:
 value = str(payload.get(field) or "").strip()
 if field == "origin" and "," in value: value = value.split(",", 1)[0].strip()
 return value

def _fetch_ip(session: requests.Session, timeout: int) -> str:
 errors: list[str] = []
 for url, field in IP_ENDPOINTS:
  try:
   response = session.get(url, timeout=timeout); response.raise_for_status(); value = _extract_ip(response.json(), field)
   if value: return value
   errors.append(f"{url}: boş IP")
  except Exception as exc:
   errors.append(f"{url}: {type(exc).__name__}")
 raise ProxyHealthError("IP doğrulama servislerine ulaşılamadı: " + ", ".join(errors))

def _direct_ip() -> str:
 try:
  with _session() as session: return _fetch_ip(session, 8)
 except Exception: return ""

def _geo_metadata(session: requests.Session, exit_ip: str, timeout: int) -> tuple[str, str, str, str]:
 errors: list[str] = []
 for template in GEO_ENDPOINTS:
  url = template.format(ip=exit_ip)
  try:
   response = session.get(url, timeout=timeout); response.raise_for_status(); data = response.json()
   if data.get("error") is True or data.get("success") is False: raise ValueError(str(data.get("reason") or data.get("message") or "geo error"))
   country = str(data.get("country_code") or data.get("country_code2") or data.get("country_code_iso2") or "").upper()
   connection = data.get("connection") if isinstance(data.get("connection"), dict) else {}
   asn = str(data.get("asn") or connection.get("asn") or "")
   org = str(data.get("org") or data.get("organization") or connection.get("org") or "")
   if country or asn or org: return country, asn, org, ""
   errors.append(f"{url}: metadata boş")
  except Exception as exc:
   errors.append(f"{url}: {type(exc).__name__}")
 return "", "", "", "Konum bilgisi alınamadı; bağlantı testi yine de geçti"

def test(identity: network_identity.NetworkIdentity, attempts: int = 3, timeout: int = 15) -> ProxyHealth:
 identity.validate(); exits: list[str] = []; latencies: list[int] = []; direct = _direct_ip()
 try:
  with _identity_session(identity) as session:
   for _ in range(max(2, attempts)):
    started = time.perf_counter(); exits.append(_fetch_ip(session, timeout)); latencies.append(round((time.perf_counter() - started) * 1000))
   if not exits[0]: raise ProxyHealthError("Proxy çıkış IP döndürmedi")
   if len(set(exits)) != 1: raise ProxyHealthError("Proxy sabit çıkış IP vermedi: " + ", ".join(sorted(set(exits))))
   if direct and exits[0] == direct: raise ProxyHealthError("Proxy devreye girmedi; çıkış IP doğrudan bağlantıyla aynı")
   median = round(statistics.median(latencies))
   if median > MAX_MEDIAN_LATENCY_MS: raise ProxyHealthError(f"Proxy çok yavaş: {median} ms")
   country, asn, org, geo_warning = _geo_metadata(session, exits[0], timeout)
   joined = f"{asn} {org}".casefold(); flags: list[str] = []
   if any(marker in joined for marker in ("hosting", "cloud", "datacenter", "digitalocean", "hetzner", "ovh", "amazon", "google cloud", "microsoft")): flags.append("datacenter_or_hosting")
   detail = "HTTPS ve sabit çıkış IP doğrulandı" + ("; " + geo_warning if geo_warning else "")
   result = ProxyHealth(fingerprint(identity), True, exits[0], country, median, datetime.now(UTC).isoformat(), detail, asn, org, tuple(flags))
 except Exception as exc:
  result = ProxyHealth(fingerprint(identity), False, exits[-1] if exits else "", "", round(statistics.median(latencies)) if latencies else 0, datetime.now(UTC).isoformat(), str(exc))
 record(result)
 return result

def latest(identity: network_identity.NetworkIdentity) -> ProxyHealth | None:
 row = _load().get(fingerprint(identity))
 if not row: return None
 row["risk_flags"] = tuple(row.get("risk_flags", ()))
 try: return ProxyHealth(**row)
 except TypeError: return None

def require_healthy(identity: network_identity.NetworkIdentity) -> ProxyHealth:
 result = latest(identity)
 if not result: raise ProxyHealthError("Proxy test edilmedi")
 try: checked = datetime.fromisoformat(result.checked_at.replace("Z", "+00:00"))
 except ValueError as exc: raise ProxyHealthError("Proxy test kaydı bozuk; yeniden test edin") from exc
 if datetime.now(UTC) - checked > MAX_AGE: raise ProxyHealthError("Proxy testi 24 saatten eski")
 if not result.ok: raise ProxyHealthError(result.detail)
 return result

def verify_browser_context(context, identity: network_identity.NetworkIdentity) -> ProxyHealth:
 expected = require_healthy(identity); errors: list[str] = []; actual = ""
 for url, field in IP_ENDPOINTS:
  try:
   response = context.request.get(url, timeout=15000)
   if not response.ok: errors.append(f"HTTP {response.status}"); continue
   actual = _extract_ip(response.json(), field)
   if actual: break
  except Exception as exc:
   errors.append(type(exc).__name__)
 if not actual: raise ProxyHealthError("Browser-context proxy testi başarısız: " + ", ".join(errors))
 if actual != expected.exit_ip: raise ProxyHealthError(f"Browser-context çıkış IP değişti: beklenen {expected.exit_ip}, görülen {actual}")
 return expected

def verify_browser_target(context, identity: network_identity.NetworkIdentity, target_url: str) -> ProxyHealth:
 expected = verify_browser_context(context, identity)
 try:
  response = context.request.get(target_url, timeout=30000, max_redirects=5)
  if int(response.status) <= 0: raise ProxyHealthError("TikTok geçerli HTTP durumu döndürmedi")
 except Exception as exc:
  text = str(exc)
  if "ERR_TUNNEL_CONNECTION_FAILED" in text or "tunnel" in text.casefold(): raise ProxyHealthError("Proxy TikTok HTTPS tüneli kuramadı") from exc
  raise ProxyHealthError(f"Proxy TikTok hedef testini geçemedi: {text}") from exc
 return expected
