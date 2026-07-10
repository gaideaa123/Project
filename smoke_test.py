from __future__ import annotations

import os
import py_compile
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def check(value: bool, text: str) -> None:
    if not value:
        raise AssertionError(text)
    print("OK:", text)


def main() -> None:
    root = Path(__file__).parent
    for filename in (
        "app.py", "app_tr.py", "oauth_helper.py", "web_uploader.py",
        "tiktok_login.py", "session_gui.py",
    ):
        py_compile.compile(str(root / filename), doraise=True)
        check(True, f"{filename} sözdizimi")

    import app
    import app_tr
    import tiktok_login
    import web_uploader
    from PySide6.QtWidgets import QApplication, QPushButton

    check(web_uploader.safe_profile_name(" Marka Türkiye ") == "Marka-T-rkiye", "güvenli profil adı")
    check(tiktok_login._session_value("sessionid=1234567890abcdef; Path=/") == "1234567890abcdef", "session cookie ayrıştırma")
    try:
        tiktok_login._session_value("kısa")
    except tiktok_login.LoginError:
        check(True, "geçersiz session reddi")
    else:
        raise AssertionError("geçersiz session reddedilmedi")

    qt = QApplication.instance() or QApplication([])
    with patch.object(app_tr.tiktok_login, "load_session", return_value=""):
        window = app_tr.TurkceAnaPencere()
        check(window.web_profiles.columnCount() == 6, "Session ID sütunu doğrudan app_tr GUI'de")
        headers = [window.web_profiles.horizontalHeaderItem(i).text() for i in range(6)]
        check(headers[3] == "Session ID", "Session ID başlığı")
        if window.web_profiles.rowCount():
            check(isinstance(window.web_profiles.cellWidget(0, 3), QPushButton), "profil Session ID düğmesi")
        window.close()

    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary); video = folder / "video.mp4"; video.write_bytes(b"not-empty")
        web_uploader.UploadRequest("test", video, "caption").validate()
        registry = app.AtomicRegistry(folder / "state.json")
        account = registry.add_account("Test")
        first = registry.add_job(account["id"], str(video), "bir", app.utc_now(), "SELF_ONLY")
        claimed, _ = registry.claim_job(first["id"])
        check(claimed["status"] == "running", "atomik iş sahiplenme")
        state = registry.snapshot(); second = dict(first)
        second.update(id="second", status="queued", run_at=app.iso(app.utc_now() - timedelta(seconds=1)))
        state["jobs"].append(second); registry._atomic_write(state)
        try:
            registry.claim_job("second")
        except app.StateError:
            check(True, "aynı profil eşzamanlı yayın engeli")
        else:
            raise AssertionError("eşzamanlı yayın engellenmedi")

    qt.quit()
    print("\nTÜM DUMAN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
