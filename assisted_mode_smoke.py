from __future__ import annotations

import inspect

import tiktok_login


def check(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)
    print("OK:", message)


def main() -> None:
    install_source = inspect.getsource(tiktok_login.install)
    writer_source = inspect.getsource(tiktok_login._native_caption_write)
    check("add_cookies" not in install_source, "session cookie enjeksiyonu yok")
    check("publish=publish" in install_source, "otomatik final Yayınla akışı korundu")
    check("approval=approval" in install_source, "GUI son onayı korundu")
    check("dispatchEvent" not in writer_source, "JavaScript sentetik input/change event yok")
    check("press_sequentially" in writer_source, "standart Playwright klavye girişi kullanılıyor")
    check("stealth" not in install_source.casefold(), "stealth/fingerprint bypass yaması yok")
    check("_INSTALL_LOCK" in install_source, "hesaplar sıralı ve izole")
    check("finally:" in install_source and "previous_writer" in install_source,
          "geçici profil wrapperları geri yükleniyor")
    print("\nOTOMATİK YAYINLA, DÜŞÜRÜLMÜŞ RİSK TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
