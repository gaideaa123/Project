from __future__ import annotations

import inspect
import os
import py_compile
import tempfile
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
        "tiktok_login.py", "copyright_dialog.py", "video_variants.py",
        "uniquizer_tab.py",
    ):
        py_compile.compile(str(root / filename), doraise=True)
        check(True, f"{filename} sözdizimi")

    import app_tr
    import copyright_dialog
    import tiktok_login
    import web_uploader
    from PySide6.QtWidgets import QApplication, QSpinBox

    flow = inspect.getsource(web_uploader.prepare_upload)
    steps = [
        "upload_file(", "dismiss_pre_caption_notice(", "fill_caption(",
        "wait_for_upload_complete(", "button.click(",
        "confirm_publish_dialog(", "wait_for_publish_result(",
    ]
    positions = [flow.index(step) for step in steps]
    check(positions == sorted(positions), "ana Paylaş → Hemen paylaş → sonuç sırası")

    check(copyright_dialog.COPYRIGHT_WARNING.search("Telif hakkı kontrolü henüz bitmedi") is not None, "Türkçe telif uyarısı")
    check(copyright_dialog.IMMEDIATE_SHARE.fullmatch("Hemen paylaş") is not None, "exact Hemen paylaş")
    check(copyright_dialog.IMMEDIATE_SHARE.fullmatch("Hemen yayınla") is not None, "exact Hemen yayınla")
    check(copyright_dialog.IMMEDIATE_SHARE.fullmatch("Share now") is not None, "exact Share now")
    check(copyright_dialog.IMMEDIATE_SHARE.fullmatch("Paylaş") is None, "genel Paylaş ikinci dialogda seçilmez")

    handler = inspect.getsource(copyright_dialog.handle)
    check('get_by_role("dialog")' in handler, "yalnız dialog scope")
    check("COPYRIGHT_WARNING.search(text)" in handler, "telif metni doğrulaması")
    check('get_by_text(IMMEDIATE_SHARE, exact=True)' in handler, "nested Hemen paylaş fallback")
    check("ancestor::*[self::button or @role='button']" in handler, "tıklanabilir parent fallback")
    check(web_uploader.confirm_publish_dialog.__module__ == "tiktok_login", "handler web uploader'a kuruldu")
    check(tiktok_login.handle_copyright_publish_dialog.__module__ == "tiktok_login", "handler delegasyonu")

    qt = QApplication.instance() or QApplication([])
    with patch.object(app_tr.tiktok_login, "has_session", return_value=False), patch.object(app_tr.tiktok_login, "has_credentials", return_value=False):
        window = app_tr.TurkceAnaPencere()
        check(len(window.azure_web_page.findChildren(QSpinBox)) == 0, "Azure + Web varyasyon sayısı yok")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            files = []
            for index in range(1, 3):
                file = folder / f"{index}.mp4"
                file.write_bytes(b"video")
                files.append(str(file))
            with patch.object(window, "account_names", return_value=["captionai", "Emre"]), patch.object(window, "refresh_web_profiles"), patch.object(window, "save_azure", return_value=True), patch.object(window, "start_publish") as start:
                window.distribute_uniquizer_outputs(files)
                expected = [
                    ("captionai", Path(files[0]).resolve()),
                    ("Emre", Path(files[1]).resolve()),
                ]
                check(window.pending_assignments == expected, "profil sırası korundu")
                start.assert_called_once_with(expected)
        window.close()
    qt.quit()
    print("\nHEMEN PAYLAŞ VE SIRALI YAYIN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
