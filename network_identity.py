from __future__ import annotations

"""Stable, operator-provided network identity per browser profile.

This module intentionally does not rotate proxies, spoof device fingerprints or
bypass platform controls. It only lets an authorized operator bind one persistent
browser profile to one fixed outbound gateway and keeps credentials in the OS
keychain.
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
            raise NetworkIdentityError("Ağ geçidi http, https veya socks5 olmalı")
        if not parsed.hostname or not parsed.port:
            raise NetworkIdentityError("Ağ geçidi host ve port içermeli")
        if parsed.username or parsed.password:
            raise NetworkIdentityError("Kullanıcı/parolayı URL içine değil ayrı alanlara girin")
        if bool(self.username) != bool(self.password):
            raise NetworkIdentityError("Ağ geçidi kullanıcı adı ve parolası birlikte girilmeli")

    def playwright_proxy(self) -> dict[str, str] | None:
        self.validate()
        if not self.server:
            return None
        value = {"server": self.server}
        if self.username:
            value["username"] = self.username
            value["password"] = self.password
        return value


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


def delete(profile: str) -> None:
    for field in ("server", "username", "password"):
        try:
            keyring.delete_password(SERVICE, _profile_key(profile, field))
        except Exception:
            pass


def proxy_for(profile: str) -> dict[str, str] | None:
    return load(profile).playwright_proxy()
