from __future__ import annotations

import os
import py_compile
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def check(value: bool, text: str) -> None:
    if not value:
        raise AssertionError(text)
    print("OK:", text)


def main() -> None:
    root = Path(__file__).parent
    for filename in (
        "app.py", "app_tr.py", "oauth_helper.py", "web_uploader.py",
        "tiktok_login.py", "video_variants.py",
    ):
        py_compile.compile(str(root / filename), doraise=True)
        check(True, f"{filename} sözdizimi")

    import app_tr
    import tiktok_login
    import video_variants
    import web_uploader
    from PySide6.QtWidgets import QApplication, QPushButton, QSpinBox

    check("Konu: Başlık üretmeyi kolaylaştıran" in app_tr.GUIDE, "orijinal guide korundu")
    check(video_variants.variant_parameters(1)[0] == 1.0, "ilk varyasyon parametresi")
    check(video_variants.variant_parameters(37) != video_variants.variant_parameters(1), "dinamik varyasyon parametreleri")
    try:
        video_variants.create_variants(Path("missing.mp4"), 0)
    except video_variants.VariantError:
        check(True, "geçersiz varyasyon sayısı reddi")
    else:
        raise AssertionError("geçersiz varyasyon sayısı reddedilmedi")

    check(tiktok_login._session_value("sessionid=1234567890abcdef; Path=/") == "1234567890abcdef", "session ayrıştırma")
    field = MagicMock(); field.evaluate.return_value = "div"; field.inner_text.return_value = "Caption"
    check(web_uploader._caption_value(field) == "Caption", "contenteditable caption doğrulama")

    qt = QApplication.instance() or QApplication([])
    with patch.object(app_tr.tiktok_login, "has_session", return_value=False), patch.object(app_tr.tiktok_login, "has_credentials", return_value=False):
        window = app_tr.TurkceAnaPencere()
        check(isinstance(window.variant_count, QSpinBox), "varyasyon sayısı alanı")
        check(window.variant_count.minimum() == 1 and window.variant_count.maximum() == 100, "1-100 varyasyon aralığı")
        add_buttons = [b for b in window.findChildren(QPushButton) if "SESSION ID İLE YENİ HESAP" in b.text()]
        check(len(add_buttons) == 1, "Session ID ile hesap ekleme düğmesi")
        check(window.web_profiles.columnCount() == 6, "profil tablosu")
        window.close()
    qt.quit()
    print("\nTÜM GUI DUMAN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
