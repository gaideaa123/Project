from __future__ import annotations

import re

import publish_verification as verification


def check(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)
    print("OK:", message)


def main() -> None:
    check(not verification.PUBLISH_SUCCESS.search("Upload complete"),
          "upload complete yayın başarısı sayılmıyor")
    check(not verification.PUBLISH_SUCCESS.search("Video yüklendi"),
          "video yüklendi yayın başarısı sayılmıyor")
    check(verification.PUBLISH_SUCCESS.fullmatch("Video yayınlandı") is not None,
          "kesin yayın mesajı kabul ediliyor")
    check(verification.PUBLISH_FAILURE.search("Something went wrong. Try again") is not None,
          "sessiz TikTok post hatası yakalanıyor")
    for label in ("Only you", "Private", "Yalnızca sen", "Sadece ben"):
        check(verification.PRIVATE_AUDIENCE.fullmatch(label) is not None,
              f"özel görünürlük yakalanıyor: {label}")
    check(verification.CONTENT_URL.search("https://www.tiktok.com/tiktokstudio/content") is not None,
          "içerik yönetimi yönlendirmesi kabul ediliyor")
    check(verification.CONTENT_URL.search("https://www.tiktok.com/tiktokstudio/upload") is None,
          "upload ekranında kalmak başarı sayılmıyor")
    source = open("publish_verification.py", encoding="utf-8").read()
    check("upload complete" not in re.findall(r'PUBLISH_SUCCESS = re.compile\((.*?)\)\n', source, re.S)[0].casefold(),
          "başarı regexinde upload-complete yok")
    print("\nKESİN WEB YAYIN DOĞRULAMA TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
