from __future__ import annotations

"""Stable one-proxy-per-profile identity with assignment and health locks."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import keyring
from platformdirs import user_data_dir

import proxy_health

SERVICE = "signaldesk-profile-network"
DATA_DIR = Path(user_data_dir("signaldesk-profile-network", "SignalDesk"))
BINDINGS = DATA_DIR / "proxy-bindings.json"
ALLOWED_SCHEMES = {"http", "https", "socks5"}


class NetworkIdentityError(RuntimeError): pass


@dataclass(frozen=True)
class NetworkIdentity:
    server: str = ""; username: str = ""; password: str = ""
    def validate(self):
        if not self.server: return
        parsed = urlparse(self.server)
        if parsed.scheme.casefold() not in ALLOWED_SCHEMES: raise NetworkIdentityError("Proxy http, https veya socks5 olmalı")
        if not parsed.hostname or not parsed.port: raise NetworkIdentityError("Proxy host ve port içermeli")
        if parsed.username or parsed.password: raise NetworkIdentityError("Credential değerlerini URL içine gömmeyin")
        if bool(self.username) != bool(self.password): raise NetworkIdentityError("Kullanıcı ve parola birlikte girilmeli")
    def playwright_proxy(self):
        self.validate()
        if not self.server: return None
        value = {"server": self.server}
        if self.username: value.update(username=self.username, password=self.password)
        return value


def parse_proxy_line(value, default_scheme="http"):
    raw=value.strip(); scheme=default_scheme
    if not raw: raise NetworkIdentityError("Boş proxy satırı")
    if "://" in raw: scheme,raw=raw.split("://",1)
    parts=raw.split(":",3)
    if len(parts) not in {2,4}: raise NetworkIdentityError("Format host:port veya host:port:kullanıcı:parola olmalı")
    host,port=parts[0].strip(),parts[1].strip()
    if scheme not in ALLOWED_SCHEMES or not host or not port.isdigit() or not 1<=int(port)<=65535: raise NetworkIdentityError("Proxy tipi/host/port geçersiz")
    user,password=(parts[2],parts[3]) if len(parts)==4 else ("","")
    result=NetworkIdentity(f"{scheme}://{host}:{port}",user,password); result.validate(); return result


def parse_proxy_list(value, default_scheme="http"):
    rows=[]
    for number,line in enumerate(value.splitlines(),1):
        if not line.strip() or line.strip().startswith("#"): continue
        try: rows.append(parse_proxy_line(line,default_scheme))
        except Exception as exc: raise NetworkIdentityError(f"Satır {number}: {exc}") from exc
    if not rows: raise NetworkIdentityError("En az bir proxy girin")
    if len({r.server for r in rows}) != len(rows): raise NetworkIdentityError("Aynı proxy iki kez kullanılamaz")
    return rows


def _key(profile,field): return f"{'-'.join(profile.strip().split()).casefold()}:{field}"
def _binding_id(identity): return hashlib.sha256(f"{identity.server}|{identity.username}".encode()).hexdigest()
def _bindings():
    try:
        data=json.loads(BINDINGS.read_text(encoding="utf-8")); return data if isinstance(data,dict) else {}
    except Exception: return {}

def _write_bindings(data):
    DATA_DIR.mkdir(parents=True,exist_ok=True); temp=BINDINGS.with_suffix(".tmp"); temp.write_text(json.dumps(data,indent=2),encoding="utf-8"); temp.replace(BINDINGS)

def load(profile):
    try: return NetworkIdentity(keyring.get_password(SERVICE,_key(profile,"server")) or "",keyring.get_password(SERVICE,_key(profile,"username")) or "",keyring.get_password(SERVICE,_key(profile,"password")) or "")
    except Exception: return NetworkIdentity()

def save(profile,identity):
    identity.validate(); data=_bindings(); old=data.get(profile.casefold()); new=_binding_id(identity) if identity.server else ""
    if old and old != new: raise NetworkIdentityError(f"{profile} başka bir proxyye kilitli. Önce atamayı açıkça kaldırın.")
    if not identity.server: delete(profile); return
    keyring.set_password(SERVICE,_key(profile,"server"),identity.server); keyring.set_password(SERVICE,_key(profile,"username"),identity.username); keyring.set_password(SERVICE,_key(profile,"password"),identity.password)
    data[profile.casefold()]=new; _write_bindings(data)

def assign_in_order(profiles,identities):
    if not profiles: raise NetworkIdentityError("Proxy atanacak hesap yok")
    if len(identities)<len(profiles): raise NetworkIdentityError(f"{len(profiles)} hesap için en az {len(profiles)} proxy gerekli")
    for identity in identities[:len(profiles)]: proxy_health.require_healthy(identity)
    result=list(zip(profiles,identities,strict=False))
    for profile,identity in result: save(profile,identity)
    return result

def delete(profile):
    for field in ("server","username","password"):
        try: keyring.delete_password(SERVICE,_key(profile,field))
        except Exception: pass
    data=_bindings(); data.pop(profile.casefold(),None); _write_bindings(data)

def proxy_for(profile):
    identity=load(profile)
    if identity.server: proxy_health.require_healthy(identity)
    return identity.playwright_proxy()
