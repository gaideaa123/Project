from __future__ import annotations

from unittest.mock import MagicMock, patch

import network_identity
import web_uploader


def check(value, message):
    if not value: raise AssertionError(message)
    print("OK:", message)


def main():
    direct = network_identity.NetworkIdentity()
    check(direct.playwright_proxy() is None, "boş ayar doğrudan bağlantı")
    fixed = network_identity.NetworkIdentity("http://127.0.0.1:8080", "user", "pass")
    check(fixed.playwright_proxy() == {"server":"http://127.0.0.1:8080","username":"user","password":"pass"}, "sabit proxy Playwright formatı")
    try: network_identity.NetworkIdentity("http://host-without-port").validate()
    except network_identity.NetworkIdentityError: check(True, "portsuz geçit reddediliyor")
    else: raise AssertionError("portsuz geçit reddedilmedi")
    try: network_identity.NetworkIdentity("http://u:p@host:8080").validate()
    except network_identity.NetworkIdentityError: check(True, "URL içine credential gömme reddediliyor")
    else: raise AssertionError("URL credential reddedilmedi")
    source = open("web_uploader.py", encoding="utf-8").read()
    check('network_identity.proxy_for(profile)' in source, "profil bazlı ağ kimliği launch akışına bağlı")
    check('options["proxy"] = proxy' in source, "proxy yalnız ayarlı profile uygulanıyor")
    check("rotate" not in source.casefold(), "IP rotasyonu yok")
    print("\nSABİT PROFİL AĞ KİMLİĞİ TESTLERİ GEÇTİ")


if __name__ == "__main__": main()
