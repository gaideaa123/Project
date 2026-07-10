from __future__ import annotations

import os
import py_compile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def check(value: bool, text: str) -> None:
    if not value:
        raise AssertionError(text)
    print("OK:", text)


def main() -> None:
    root = Path(__file__).parent
    for filename in ("app.py", "app_tr.py", "oauth_helper.py", "web_uploader.py", "tiktok_login.py"):
        py_compile.compile(str(root / filename), doraise=True)
        check(True, f"{filename} sözdizimi")

    import app_tr
    import tiktok_login
    from PySide6.QtWidgets import QApplication, QPushButton

    check(tiktok_login._session_value("sessionid=1234567890abcdef; Path=/") == "1234567890abcdef", "session ayrıştırma")
    try:
        tiktok_login._session_value("kısa")
    except tiktok_login.LoginError:
        check(True, "geçersiz session reddi")
    else:
        raise AssertionError("geçersiz session reddedilmedi")

    qt = QApplication.instance() or QApplication([])
    with patch.object(app_tr.tiktok_login, "has_session", return_value=False), patch.object(app_tr.tiktok_login, "has_credentials", return_value=False):
        window = app_tr.TurkceAnaPencere()
        check(window.web_profiles.columnCount() == 6, "app_tr doğrudan altı sütun")
        headers = [window.web_profiles.horizontalHeaderItem(i).text() for i in range(6)]
        check(headers == ["Seç", "Profil", "Giriş", "Session ID", "Durum", "İşlem"], "profil başlıkları")
        for row in range(window.web_profiles.rowCount()):
            check(isinstance(window.web_profiles.cellWidget(row, 3), QPushButton), "Session düğmesi")
            check(isinstance(window.web_profiles.cellWidget(row, 5), QPushButton), "Yayın düğmesi")
        window.refresh_web_profiles()
        check(window.isVisible() is False, "offscreen pencere yaşam döngüsü")
        window.close()
    qt.quit()
    print("\nTÜM GUI DUMAN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
