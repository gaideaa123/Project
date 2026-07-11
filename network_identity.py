from __future__ import annotations

"""Stable, operator-provided network identity per browser profile.

No proxy rotation or fingerprint spoofing is performed. Each account is bound to
one fixed proxy and keeps that assignment across runs. Credentials are stored in
the operating-system keychain, never in project files.
"""

from dataclasses import dataclass
from urllib.parse import urlparse

import keyring

SERVICE = "signaldesk-profile-network"
ALLOWED_SCHEMES = {"http", "https", "socks5"}


class NetworkIdentityError(RuntimeError):
    pass


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
        if not parsed.hostname or not parsed.port:
            raise NetworkIdentityError("Proxy host ve port içermeli")
        if parsed.username or parsed.password:
            raise NetworkIdentityError("Kullanıcı/parolayı proxy URL içine gömmeyin")
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


def parse_proxy_line(value: str, default_scheme: str = "http") -> NetworkIdentity:
    """Parse host:port:user:pass or scheme://host:port:user:pass."""
    raw = value.strip()
    if not raw:
        raise NetworkIdentityError("Boş proxy satırı")
    scheme = default_scheme
    if "://" in raw:
        scheme, raw = raw.split("://", 1)
    if scheme.casefold() not in ALLOWED_SCHEMES:
        raise NetworkIdentityError(f"Desteklenmeyen proxy tipi: {scheme}")
    parts = raw.split(":", 3)
    if len(parts) not in {2, 4}:
        raise NetworkIdentityError(
            "Proxy formatı host:port veya host:port:kullanıcı:parola olmalı"
        )
    host, port = parts[0].strip(), parts[1].strip()
    if not host or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise NetworkIdentityError("Proxy host/port geçersiz")
    username, password = (parts[2], parts[3]) if len(parts) == 4 else ("", "")
    identity = NetworkIdentity(f"{scheme.casefold()}://{host}:{port}", username, password)
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
    servers = [item.server for item in identities]
    if len(servers) != len(set(servers)):
        raise NetworkIdentityError("Aynı proxy listede birden fazla kez kullanılamaz")
    return identities


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
        raise NetworkIdentityError(
            f"{len(profiles)} hesap var ama {len(identities)} proxy girildi. Her hesap için bir proxy gerekli."
        )
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
