from __future__ import annotations

"""External, browser-context, and target-specific proxy verification."""

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
 asn: str = ""
 org: str = ""
 risk_flags: tuple[str, ...] = ()

def fingerprint(identity) -> str:
 return hashlib.sha256(f"{identity.server}|{identity.username}".encode()).hexdigest()

def _url(identity) -> str:
 parsed = urlparse(identity.server)
 auth = f"{quote(identity.username, safe='')}:{quote(identity.password, safe='')}@" if identity.username else ""
 return f"{parsed.scheme}://{auth}{parsed.hostname}:{parsed.port}"

def _proxies(identity) -> dict[str, str]:
 value = _url(identity)
 return {"http": value, "https": value}

def _load() -> dict:
 try:
  data = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
  return data if isinstance(data, dict) else {}
 except Exception:
  return {}

def record(result: ProxyHealth) -> None:
 DATA_DIR.mkdir(parents=True, exist_ok=True)
 data = _load(); row = asdict(result); row["risk_flags"] = list(result.risk_flags)
 data[result.fingerprint] = row
 temporary = HEALTH_FILE.with_suffix(".tmp")
 temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
 temporary.replace(HEALTH_FILE)

def _direct_ip() -> str:
 try:
  response = requests.get(IP_URL, timeout=8); response.raise_for_status()
  return str(response.json().get("ip") or "")
 except Exception:
  return ""

def test(identity, attempts: int = 3, timeout: int = 15) -> ProxyHealth:
 identity.validate(); exits: list[str] = []; latencies: list[int] = []
 proxy = _proxies(identity); direct = _direct_ip()
 try:
  for _ in range(attempts):
   started = time.perf_counter()
   response = requests.get(IP_URL, proxies=proxy, timeout=timeout); response.raise_for_status()
   exits.append(str(response.json().get("ip") or ""))
   latencies.append(round((time.perf_counter() - started) * 1000))
  if not exits[0] or len(set(exits)) != 1:
   raise ProxyHealthError("Proxy sabit çıkış IP vermedi")
  if direct and exits[0] == direct:
   raise ProxyHealthError("Proxy doğrudan IP ile aynı")
  geo = requests.get(GEO_URL, proxies=proxy, timeout=timeout); geo.raise_for_status(); data = geo.json()
  country = str(data.get("country_code") or "").upper(); asn = str(data.get("asn") or ""); org = str(data.get("org") or "")
  median = round(statistics.median(latencies)); flags: list[str] = []; joined = f"{asn} {org}".casefold()
  if any(value in joined for value in ("hosting", "cloud", "datacenter", "digitalocean", "hetzner", "ovh", "amazon", "google cloud", "microsoft")):
   flags.append("datacenter_or_hosting")
  if median > MAX_MEDIAN_LATENCY_MS:
   raise ProxyHealthError(f"Proxy çok yavaş: {median} ms")
  result = ProxyHealth(fingerprint(identity), True, exits[0], country, median, datetime.now(UTC).isoformat(), "HTTPS ve sabit IP doğrulandı", asn, org, tuple(flags))
 except Exception as exc:
  result = ProxyHealth(fingerprint(identity), False, exits[-1] if exits else "", "", round(statistics.median(latencies)) if latencies else 0, datetime.now(UTC).isoformat(), str(exc))
 record(result)
 return result

def latest(identity) -> ProxyHealth | None:
 row = _load().get(fingerprint(identity))
 if not row:
  return None
 row["risk_flags"] = tuple(row.get("risk_flags", ()))
 try:
  return ProxyHealth(**row)
 except TypeError:
  return None

def require_healthy(identity) -> ProxyHealth:
 result = latest(identity)
 if not result:
  raise ProxyHealthError("Proxy test edilmedi")
 try:
  checked = datetime.fromisoformat(result.checked_at.replace("Z", "+00:00"))
 except ValueError as exc:
  raise ProxyHealthError("Proxy test kaydı bozuk; yeniden test edin") from exc
 if datetime.now(UTC) - checked > MAX_AGE:
  raise ProxyHealthError("Proxy testi 24 saatten eski")
 if not result.ok:
  raise ProxyHealthError(result.detail)
 return result

def verify_browser_context(context, identity) -> ProxyHealth:
 """Require the Playwright context to use the exit IP seen in Proxy Listesi."""
 expected = require_healthy(identity)
 try:
  response = context.request.get(IP_URL, timeout=15000)
  if not response.ok:
   raise ProxyHealthError(f"Browser-context IP testi HTTP {response.status}")
  actual = str(response.json().get("ip") or "")
 except Exception as exc:
  raise ProxyHealthError(f"Browser-context proxy testi başarısız: {exc}") from exc
 if actual != expected.exit_ip:
  raise ProxyHealthError(f"Browser-context çıkış IP değişti: beklenen {expected.exit_ip}, görülen {actual}")
 return expected

def verify_browser_target(context, identity, target_url: str) -> ProxyHealth:
 """Prove the same proxy can establish a tunnel to the actual publish host."""
 expected = verify_browser_context(context, identity)
 try:
  response = context.request.get(target_url, timeout=30000, max_redirects=5)
  status = int(response.status)
  if status <= 0:
   raise ProxyHealthError("TikTok geçerli HTTP durumu döndürmedi")
 except Exception as exc:
  text = str(exc)
  if "ERR_TUNNEL_CONNECTION_FAILED" in text or "tunnel" in text.casefold():
   raise ProxyHealthError("Proxy TikTok HTTPS tüneli kuramadı") from exc
  raise ProxyHealthError(f"Proxy TikTok hedef testini geçemedi: {text}") from exc
 return expected
