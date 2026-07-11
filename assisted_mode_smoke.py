from __future__ import annotations

"""Behavioral smoke tests for Session ID bootstrap and automatic publishing."""

import inspect
from unittest.mock import patch

import tiktok_login


class FakeContext:
    def __init__(self, cookies=None):
        self.cookie_rows = list(cookies or [])
        self.added = []

    def cookies(self, urls=None):
        assert urls == ["https://www.tiktok.com"]
        return list(self.cookie_rows)

    def add_cookies(self, rows):
        self.added.extend(rows)


def check(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)
    print("OK:", message)


def main() -> None:
    install_source = inspect.getsource(tiktok_login.install)
    writer_source = inspect.getsource(tiktok_login._native_caption_write)

    existing = FakeContext([{"name": "sessionid", "value": "existing-session"}])
    with patch.object(tiktok_login, "load_session", return_value="saved-session"):
        check(tiktok_login.bootstrap_session(existing, "profil") is False,
              "mevcut kalıcı profil sessionı korunuyor")
        check(existing.added == [], "mevcut session yeniden enjekte edilmiyor")

    existing_ss = FakeContext([{"name": "sessionid_ss", "value": "existing-secure-session"}])
    with patch.object(tiktok_login, "load_session", return_value="saved-session"):
        check(tiktok_login.bootstrap_session(existing_ss, "profil") is False,
              "sessionid_ss kalıcı session olarak tanınıyor")

    empty = FakeContext()
    with patch.object(tiktok_login, "load_session", return_value="saved-session"):
        check(tiktok_login.bootstrap_session(empty, "profil") is True,
              "boş profil Session ID ile bootstrap ediliyor")
    check(len(empty.added) == 1, "yalnız bir bootstrap cookie ekleniyor")
    cookie = empty.added[0]
    check(cookie["name"] == "sessionid" and cookie["domain"] == ".tiktok.com",
          "bootstrap cookie kapsamı doğru")
    check(cookie["secure"] is True and cookie["httpOnly"] is True,
          "bootstrap cookie güvenlik bayrakları doğru")

    missing = FakeContext()
    with patch.object(tiktok_login, "load_session", return_value=""):
        check(tiktok_login.bootstrap_session(missing, "profil") is False,
              "kayıtlı Session ID yoksa cookie eklenmiyor")
        check(missing.added == [], "boş secret ile sahte session oluşturulmuyor")

    check("publish=publish" in install_source and "approval=approval" in install_source,
          "GUI onayı ve otomatik final Yayınla korunuyor")
    check("dispatchEvent" not in writer_source and "press_sequentially" in writer_source,
          "caption JavaScript event yerine klavye aksiyonuyla yazılıyor")
    check("finally:" in install_source and "previous_writer" in install_source,
          "profil wrapperları hata halinde geri yükleniyor")
    print("\nSESSION BOOTSTRAP DAVRANIŞ TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
