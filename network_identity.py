from __future__ import annotations

"""Stable, operator-provided network identity per account."""

from dataclasses import dataclass
from urllib.parse import quote, unquote, urlparse

import keyring

SERVICE = "signaldesk-profile-network"
ALLOWED_SCHEMES = {"http", "https", "socks5"}

class NetworkIdentityError(RuntimeError):
 pass

def _authority_host(hostname: str) -> str:
 return f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname

@dataclass(frozen=True)
class NetworkIdentity:
 server: str = ""
 username: str = ""
 password: str = ""

 def validate(self) -> None:
  if not self.server:
   return
  parsed = urlparse(self.server)
  if parsed.scheme.casefold() not in ALLOWED_SCHEMES:
   raise NetworkIdentityError("Proxy http, https veya socks5 olmalı")
  try:
   port = parsed.port
  except ValueError as exc:
   raise NetworkIdentityError("Proxy portu geçersiz") from exc
  if not parsed.hostname or not port:
   raise NetworkIdentityError("Proxy host ve port içermeli")
  if parsed.username or parsed.password:
   raise NetworkIdentityError("Kullanıcı/parolayı kayıtlı server alanına gömmeyin")
  if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
   raise NetworkIdentityError("Proxy server yalnız scheme://host:port içermeli")
  if bool(self.username) != bool(self.password):
   raise NetworkIdentityError("Proxy kullanıcı adı ve parolası birlikte girilmeli")

 def playwright_proxy(self) -> dict[str, str] | None:
  self.validate()
  if not self.server:
   return None
  value = {"server": self.server}
  if self.username:
   value["username"] = self.username
   value["password"] = self.password
  return value

def _from_url(raw: str) -> NetworkIdentity:
 parsed = urlparse(raw)
 scheme = parsed.scheme.casefold()
 if scheme not in ALLOWED_SCHEMES:
  raise NetworkIdentityError(f"Desteklenmeyen proxy tipi: {parsed.scheme}")
 try:
  port = parsed.port
 except ValueError as exc:
  raise NetworkIdentityError("Proxy portu geçersiz") from exc
 if not parsed.hostname or not port:
  raise NetworkIdentityError("Proxy URL host ve port içermeli")
 if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
  raise NetworkIdentityError("Proxy URL sonunda path, query veya fragment olamaz")
 username = unquote(parsed.username or "")
 password = unquote(parsed.password or "")
 if bool(username) != bool(password):
  raise NetworkIdentityError("Proxy URL kullanıcı adı ve parolayı birlikte içermeli")
 host = _authority_host(parsed.hostname)
 identity = NetworkIdentity(f"{scheme}://{host}:{port}", username, password)
 identity.validate()
 return identity

def parse_proxy_line(value: str, default_scheme: str = "http") -> NetworkIdentity:
 """Accept scheme://user:pass@host:port or host:port:user:pass."""
 raw = value.strip()
 if not raw:
  raise NetworkIdentityError("Boş proxy satırı")
 if "://" in raw:
  return _from_url(raw)
 scheme = default_scheme.strip().casefold()
 if scheme not in ALLOWED_SCHEMES:
  raise NetworkIdentityError(f"Desteklenmeyen proxy tipi: {scheme}")
 parts = raw.split(":", 3)
 if len(parts) not in {2, 4}:
  raise NetworkIdentityError("Proxy; scheme://kullanıcı:parola@host:port veya host:port:kullanıcı:parola olmalı")
 host, port_text = parts[0].strip(), parts[1].strip()
 if not host or not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
  raise NetworkIdentityError("Proxy host/port geçersiz")
 username, password = (parts[2].strip(), parts[3]) if len(parts) == 4 else ("", "")
 if len(parts) == 4 and (not username or not password):
  raise NetworkIdentityError("Proxy kullanıcı adı ve parolası boş olamaz")
 identity = NetworkIdentity(f"{scheme}://{host}:{int(port_text)}", username, password)
 identity.validate()
 return identity

def parse_proxy_list(value: str, default_scheme: str = "http") -> list[NetworkIdentity]:
 identities: list[NetworkIdentity] = []
 for line_number, line in enumerate(value.splitlines(), 1):
  stripped = line.strip()
  if not stripped or stripped.startswith("#"):
   continue
  try:
   identities.append(parse_proxy_line(stripped, default_scheme))
  except NetworkIdentityError as exc:
   raise NetworkIdentityError(f"Satır {line_number}: {exc}") from exc
 if not identities:
  raise NetworkIdentityError("En az bir proxy girin")
 endpoints = [(item.server.casefold(), item.username) for item in identities]
 if len(endpoints) != len(set(endpoints)):
  raise NetworkIdentityError("Aynı proxy listede birden fazla kez kullanılamaz")
 return identities

def proxy_url(identity: NetworkIdentity) -> str:
 identity.validate()
 if not identity.server:
  return ""
 parsed = urlparse(identity.server)
 scheme = "socks5h" if parsed.scheme.casefold() == "socks5" else parsed.scheme
 auth = ""
 if identity.username:
  auth = f"{quote(identity.username, safe='')}:{quote(identity.password, safe='')}@"
 return f"{scheme}://{auth}{_authority_host(parsed.hostname or '')}:{parsed.port}"

def requests_proxies(identity: NetworkIdentity) -> dict[str, str] | None:
 value = proxy_url(identity)
 return {"http": value, "https": value} if value else None

def _profile_key(profile: str, field: str) -> str:
 clean = "-".join(profile.strip().split()).casefold()
 if not clean:
  raise NetworkIdentityError("Profil adı boş")
 return f"{clean}:{field}"

def load(profile: str) -> NetworkIdentity:
 try:
  return NetworkIdentity(
   keyring.get_password(SERVICE, _profile_key(profile, "server")) or "",
   keyring.get_password(SERVICE, _profile_key(profile, "username")) or "",
   keyring.get_password(SERVICE, _profile_key(profile, "password")) or "",
  )
 except Exception:
  return NetworkIdentity()

def save(profile: str, identity: NetworkIdentity) -> None:
 identity.validate()
 if not identity.server:
  delete(profile)
  return
 keyring.set_password(SERVICE, _profile_key(profile, "server"), identity.server)
 keyring.set_password(SERVICE, _profile_key(profile, "username"), identity.username)
 keyring.set_password(SERVICE, _profile_key(profile, "password"), identity.password)

def assign_in_order(profiles: list[str], identities: list[NetworkIdentity]) -> list[tuple[str, NetworkIdentity]]:
 if not profiles:
  raise NetworkIdentityError("Proxy atanacak hesap yok")
 if len(identities) < len(profiles):
  raise NetworkIdentityError(f"{len(profiles)} hesap var ama {len(identities)} proxy girildi. Her hesap için bir proxy gerekli.")
 assignments = list(zip(profiles, identities, strict=False))
 for profile, identity in assignments:
  save(profile, identity)
 return assignments

def delete(profile: str) -> None:
 for field in ("server", "username", "password"):
  try:
   keyring.delete_password(SERVICE, _profile_key(profile, field))
  except Exception:
   pass

def proxy_for(profile: str) -> dict[str, str] | None:
 return load(profile).playwright_proxy()
