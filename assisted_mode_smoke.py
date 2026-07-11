from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import tiktok_login


def check(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)
    print("OK:", message)


def main() -> None:
    install_source = inspect.getsource(tiktok_login.install)
    writer_source = inspect.getsource(tiktok_login._native_caption_write)
    bootstrap_source = inspect.getsource(tiktok_login.bootstrap_session)
    check("publish=publish" in install_source, "otomatik final Yayınla akışı korundu")
    check("approval=approval" in install_source, "GUI son onayı korundu")
    check("dispatchEvent" not in writer_source, "JavaScript sentetik input/change event yok")
    check("press_sequentially" in writer_source, "standart klavye girişi kullanılıyor")
    check("_existing_session_cookie" in bootstrap_source, "önce kalıcı profil session kontrol ediliyor")
    check("add_cookies" in bootstrap_source, "Session ID bootstrap mevcut")
    check("stealth" not in install_source.casefold(), "stealth/fingerprint bypass yaması yok")

    existing = MagicMock()
    existing.cookies.return_value = [{"name": "sessionid", "value": "existing-session"}]
    with patch.object(tiktok_login, "load_session", return_value="saved-session"):
        check(tiktok_login.bootstrap_session(existing, "profil") is False,
              "mevcut profil sessionı her çalıştırmada ezilmiyor")
        existing.add_cookies.assert_not_called()

    empty = MagicMock()
    empty.cookies.return_value = []
    with patch.object(tiktok_login, "load_session", return_value="saved-session"):
        check(tiktok_login.bootstrap_session(empty, "profil") is True,
              "boş profil Session ID ile bir kez bootstrap ediliyor")
        empty.add_cookies.assert_called_once()

    check("finally:" in install_source and "previous_writer" in install_source,
          "geçici profil wrapperları geri yükleniyor")
    print("\nSESSION ID BOOTSTRAP + OTOMATİK YAYIN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
