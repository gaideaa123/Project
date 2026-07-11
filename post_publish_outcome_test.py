from __future__ import annotations

from post_publish_outcome import is_published_review_notice


def main() -> None:
 assert is_published_review_notice(RuntimeError(
  "Gönderi yayınlandı ancak erişim riski görüldü: inceleniyor"
 ))
 assert is_published_review_notice(RuntimeError(
  "Gönderi yayınlandı ancak erişim riski görüldü: incelemede"
 ))
 assert not is_published_review_notice(RuntimeError("Gönderi yayınlanamadı: inceleniyor"))
 assert not is_published_review_notice(RuntimeError("Erişim riski görüldü: kısıtlı"))
 assert not is_published_review_notice(RuntimeError("TikTok yayın hatası gösterdi"))
 print("OK: yalnız yayınlanmış inceleniyor durumu başarı sayılıyor")


if __name__ == "__main__":
 main()
