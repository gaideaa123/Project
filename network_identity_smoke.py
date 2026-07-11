from __future__ import annotations

from unittest.mock import patch

import network_identity


def check(value, message):
    if not value:
        raise AssertionError(message)
    print("OK:", message)


def main():
    parsed = network_identity.parse_proxy_line("127.0.0.1:8080:user:pass")
    check(parsed.server == "http://127.0.0.1:8080", "dört parçalı proxy parse")
    check(parsed.username == "user" and parsed.password == "pass", "proxy credential parse")
    socks = network_identity.parse_proxy_line("10.0.0.1:1080:u:p", "socks5")
    check(socks.server == "socks5://10.0.0.1:1080", "seçilen proxy tipi uygulanıyor")
    values = network_identity.parse_proxy_list(
        "1.1.1.1:8001:a:b\n2.2.2.2:8002:c:d\n# yorum"
    )
    check(len(values) == 2, "çok satırlı proxy listesi parse")
    try:
        network_identity.parse_proxy_list("1.1.1.1:8001:a:b\n1.1.1.1:8001:c:d")
    except network_identity.NetworkIdentityError:
        check(True, "aynı proxy iki hesaba atanamıyor")
    else:
        raise AssertionError("duplicate proxy reddedilmedi")
    saved = []
    with patch.object(network_identity, "save", side_effect=lambda p, i: saved.append((p, i.server))):
        assignments = network_identity.assign_in_order(["A", "B"], values)
    check(len(assignments) == 2 and [row[0] for row in saved] == ["A", "B"],
          "hesap sırasına bire bir proxy ataması")
    try:
        network_identity.assign_in_order(["A", "B", "C"], values)
    except network_identity.NetworkIdentityError:
        check(True, "proxy sayısı hesap sayısından azsa engelleniyor")
    else:
        raise AssertionError("eksik proxy listesi kabul edildi")
    source = open("web_uploader.py", encoding="utf-8").read()
    check("network_identity.proxy_for(profile)" in source, "proxy browser launch akışına bağlı")
    check("rotate" not in source.casefold(), "proxy rotasyonu yok")
    print("\nHESAP BAŞINA SABİT PROXY TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
