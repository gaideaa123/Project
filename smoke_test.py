from __future__ import annotations

import inspect
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
    worker_source = inspect.getsource(app_tr.PublishWorker.run)
    check("video_variants.create_variants" in worker_source, "app_tr cold-open motor bağlantısı")
    check("self.variant_count" in worker_source, "dinamik varyasyon sayısı bağlantısı")

    chain = video_variants.visual_chain("0", 1.0, 1.02, 1.0, 1.0, 0.0, True)
    check("setpts=PTS-STARTPTS" in chain, "cold-open zaman tabanı")
    check("setsar=1" in chain and "fps=30" in chain, "concat SAR ve FPS normalizasyonu")
    signature = inspect.signature(video_variants.create_variants)
    check(signature.parameters["cold_open"].default is True, "cold-open varsayılan açık")

    check(tiktok_login._session_value("sessionid=1234567890abcdef; Path=/") == "1234567890abcdef", "session ayrıştırma")
    field = MagicMock(); field.evaluate.return_value = "div"; field.inner_text.return_value = "Caption"
    check(web_uploader._caption_value(field) == "Caption", "caption doğrulama")

    qt = QApplication.instance() or QApplication([])
    with patch.object(app_tr.tiktok_login, "has_session", return_value=False), patch.object(app_tr.tiktok_login, "has_credentials", return_value=False):
        window = app_tr.TurkceAnaPencere()
        check(isinstance(window.variant_count, QSpinBox), "GUI varyasyon sayısı")
        check(window.variant_count.minimum() == 1 and window.variant_count.maximum() == 100, "1-100 cold-open varyasyon aralığı")
        buttons = [button.text() for button in window.findChildren(QPushButton)]
        check(any("VARYASYONLARI OLUŞTUR" in text for text in buttons), "GUI cold-open üretim akışı")
        window.close()
    qt.quit()
    print("\nTÜM COLD-OPEN GUI TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
