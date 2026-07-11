from __future__ import annotations

"""External and same-browser-context proxy health verification."""

import hashlib,json,statistics,time
from dataclasses import asdict,dataclass
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import quote,urlparse
import requests
from platformdirs import user_data_dir
UTC=timezone.utc; DATA_DIR=Path(user_data_dir("signaldesk-profile-network","SignalDesk")); HEALTH_FILE=DATA_DIR/"proxy-health.json"; IP_URL="https://api.ipify.org?format=json"; GEO_URL="https://ipapi.co/json/"; MAX_AGE=timedelta(hours=24); MAX_MEDIAN_LATENCY_MS=5000
class ProxyHealthError(RuntimeError):pass
@dataclass(frozen=True)
class ProxyHealth:
    fingerprint:str;ok:bool;exit_ip:str;country_code:str;median_latency_ms:int;checked_at:str;detail:str="";asn:str="";org:str="";risk_flags:tuple[str,...]=()
def fingerprint(identity):return hashlib.sha256(f"{identity.server}|{identity.username}".encode()).hexdigest()
def _url(identity):
    p=urlparse(identity.server);auth=f"{quote(identity.username,safe='')}:{quote(identity.password,safe='')}@" if identity.username else "";return f"{p.scheme}://{auth}{p.hostname}:{p.port}"
def _proxies(identity):value=_url(identity);return {"http":value,"https":value}
def _load():
    try:data=json.loads(HEALTH_FILE.read_text(encoding="utf-8"));return data if isinstance(data,dict) else {}
    except Exception:return {}
def record(result):
    DATA_DIR.mkdir(parents=True,exist_ok=True);data=_load();row=asdict(result);row["risk_flags"]=list(result.risk_flags);data[result.fingerprint]=row;tmp=HEALTH_FILE.with_suffix(".tmp");tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8");tmp.replace(HEALTH_FILE)
def _direct_ip():
    try:r=requests.get(IP_URL,timeout=8);r.raise_for_status();return str(r.json().get("ip") or "")
    except Exception:return ""
def test(identity,attempts=3,timeout=15):
    identity.validate();exits=[];latencies=[];proxy=_proxies(identity);direct=_direct_ip()
    try:
        for _ in range(attempts):
            start=time.perf_counter();r=requests.get(IP_URL,proxies=proxy,timeout=timeout);r.raise_for_status();exits.append(str(r.json().get("ip") or ""));latencies.append(round((time.perf_counter()-start)*1000))
        if not exits[0] or len(set(exits))!=1:raise ProxyHealthError("Proxy sabit çıkış IP vermedi")
        if direct and exits[0]==direct:raise ProxyHealthError("Proxy doğrudan IP ile aynı")
        geo=requests.get(GEO_URL,proxies=proxy,timeout=timeout);geo.raise_for_status();data=geo.json();country=str(data.get("country_code") or "").upper();asn=str(data.get("asn") or "");org=str(data.get("org") or "");median=round(statistics.median(latencies));flags=[];joined=f"{asn} {org}".casefold()
        if any(x in joined for x in ("hosting","cloud","datacenter","digitalocean","hetzner","ovh","amazon","google cloud","microsoft")):flags.append("datacenter_or_hosting")
        if median>MAX_MEDIAN_LATENCY_MS:raise ProxyHealthError(f"Proxy çok yavaş: {median} ms")
        result=ProxyHealth(fingerprint(identity),True,exits[0],country,median,datetime.now(UTC).isoformat(),"HTTPS ve sabit IP doğrulandı",asn,org,tuple(flags))
    except Exception as exc:result=ProxyHealth(fingerprint(identity),False,exits[-1] if exits else "","",round(statistics.median(latencies)) if latencies else 0,datetime.now(UTC).isoformat(),str(exc))
    record(result);return result
def latest(identity):
    row=_load().get(fingerprint(identity))
    if not row:return None
    row["risk_flags"]=tuple(row.get("risk_flags",()))
    try:return ProxyHealth(**row)
    except TypeError:return None
def require_healthy(identity):
    result=latest(identity)
    if not result:raise ProxyHealthError("Proxy test edilmedi")
    checked=datetime.fromisoformat(result.checked_at.replace("Z","+00:00"))
    if datetime.now(UTC)-checked>MAX_AGE:raise ProxyHealthError("Proxy testi 24 saatten eski")
    if not result.ok:raise ProxyHealthError(result.detail)
    return result
def verify_browser_context(context,identity):
    """Verify the actual Playwright context uses the tested exit IP."""
    expected=require_healthy(identity)
    try:
        response=context.request.get(IP_URL,timeout=15000)
        if not response.ok:raise ProxyHealthError(f"Browser-context IP testi HTTP {response.status}")
        actual=str(response.json().get("ip") or "")
    except Exception as exc:raise ProxyHealthError(f"Browser-context proxy testi başarısız: {exc}") from exc
    if actual!=expected.exit_ip:raise ProxyHealthError(f"Browser-context çıkış IP değişti: beklenen {expected.exit_ip}, görülen {actual}")
    return expected
