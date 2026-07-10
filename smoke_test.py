from __future__ import annotations

import os
import py_compile
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def check(value: bool, text: str) -> None:
    if not value: raise AssertionError(text)
    print("OK:", text)


def main() -> None:
    root = Path(__file__).parent
    for filename in ("app.py", "app_tr.py", "oauth_helper.py", "web_uploader.py", "tiktok_login.py", "video_variants.py"):
        py_compile.compile(str(root / filename), doraise=True); check(True, f"{filename} sözdizimi")

    import app_tr
    import tiktok_login
    import video_variants
    import web_uploader
    from PySide6.QtWidgets import QApplication, QPushButton

    check(len(video_variants.PRESETS) == 5, "beş varyasyon preset'i")
    check(tiktok_login._session_value("sessionid=1234567890abcdef; Path=/") == "1234567890abcdef", "session ayrıştırma")

    field = MagicMock()
    field.evaluate.return_value = "div"
    field.inner_text.return_value = "Başlık burada #bir #iki"
    check(web_uploader._caption_value(field) == "Başlık burada #bir #iki", "contenteditable caption okuma")
    textarea = MagicMock()
    textarea.evaluate.return_value = "textarea"
    textarea.input_value.return_value = "Caption"
    check(web_uploader._caption_value(textarea) == "Caption", "textarea caption okuma")

    qt = QApplication.instance() or QApplication([])
    with patch.object(app_tr.tiktok_login, "has_session", return_value=False), patch.object(app_tr.tiktok_login, "has_credentials", return_value=False):
        window = app_tr.TurkceAnaPencere()
        check(window.web_profiles.columnCount() == 6, "app_tr profil tablosu")
        check(window.variant_progress.maximum() == 100, "varyasyon ilerleme çubuğu")
        for row in range(window.web_profiles.rowCount()):
            check(isinstance(window.web_profiles.cellWidget(row, 3), QPushButton), "Session düğmesi")
            check(isinstance(window.web_profiles.cellWidget(row, 5), QPushButton), "Varyasyon + Web düğmesi")
        window.close()
    qt.quit()
    print("\nTÜM GUI DUMAN TESTLERİ GEÇTİ")


if __name__ == "__main__": main()
