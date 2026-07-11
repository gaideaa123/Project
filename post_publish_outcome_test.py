from __future__ import annotations

from post_publish_outcome import is_published_review_notice


def main() -> None:
 accepted = (
  "Gönderi yayınlandı ancak erişim riski görüldü: inceleniyor",
  "Gönderi başarıyla yayınlandı, ancak erişim riski görüldü: incelemede",
  "Video paylaşıldı ancak erişim riski görüldü:\nunder review",
 )
 for message in accepted:
  assert is_published_review_notice(RuntimeError(message)), message

 rejected = (
  "Gönderi yayınlanamadı: inceleniyor",
  "Erişim riski görüldü: kısıtlı",
  "Gönderi hazırlanıyor ancak erişim riski görüldü: inceleniyor",
  "TikTok yayın hatası gösterdi",
  "Hesap kısıtlandı",
 )
 for message in rejected:
  assert not is_published_review_notice(RuntimeError(message)), message

 print("OK: yalnız kesin yayın + inceleme sonucu sıradaki hesaba geçiriliyor")


if __name__ == "__main__":
 main()
