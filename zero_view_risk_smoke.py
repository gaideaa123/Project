from __future__ import annotations

import publication_guard as guard


def check(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)
    print("OK:", message)


def main() -> None:
    for label in ("Only you", "Private", "Yalnızca ben", "Sadece ben"):
        check(guard.PRIVATE_AUDIENCE.fullmatch(label) is not None,
              f"özel görünürlük yakalanıyor: {label}")
    check(guard.HARD_BLOCK.search("Your account is restricted") is not None,
          "hesap kısıtı yakalanıyor")
    check(guard.CHECK_PENDING.search("Copyright check is in progress") is not None,
          "tamamlanmamış içerik kontrolü yakalanıyor")
    check(guard.POST_FAILURE.search("Something went wrong. Try again") is not None,
          "sessiz yayın hatası yakalanıyor")
    check(guard.POST_SUCCESS.search("Video yayınlandı") is not None,
          "kesin yayın mesajı kabul ediliyor")
    check(guard.POST_SUCCESS.search("Upload complete") is None,
          "upload tamamlanması yayın başarısı sayılmıyor")
    check(guard.CONTENT_DESTINATION.search("https://www.tiktok.com/tiktokstudio/content") is not None,
          "bilinen içerik sayfası kabul ediliyor")
    check(guard.CONTENT_DESTINATION.search("https://www.tiktok.com/tiktokstudio/upload") is None,
          "upload ekranında kalmak başarı sayılmıyor")
    print("\nSIFIR İZLENME RİSK KAPILARI TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
