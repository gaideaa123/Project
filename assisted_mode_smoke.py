from __future__ import annotations

import inspect

import tiktok_login


def check(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)
    print("OK:", message)


def main() -> None:
    source = inspect.getsource(tiktok_login.install)
    check("add_cookies" not in source, "session cookie enjeksiyonu yok")
    check("publish=False" in source, "otomatik son Publish tıklaması kapalı")
    check("approval=None" in source, "sentetik yayın onayı kullanılmıyor")
    check("stealth" not in source.casefold(), "stealth/bypass yaması yok")
    check("_INSTALL_LOCK" in source, "hesaplar sıralı ve izole")
    check("finally:" in source and "original_wait" in source, "geçici wrapper geri yükleniyor")
    check("_session_value" in dir(tiktok_login), "eski profil UI uyumluluğu korunuyor")
    print("\nDÜŞÜK RİSKLİ YARDIMLI WEB MODU TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
