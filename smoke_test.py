from __future__ import annotations

import inspect
import os
import py_compile
import tempfile
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

    screenshot_text = (
        "Paylaşmaya devam edilsin mi? "
        "Telif hakkı kontrolü eksik. Videonuzu şimdi paylaşmak kontrolü durdurur. "
        "Videonuzu hâlâ potansiyel sorunlar bakımından kontrol ediyoruz. "
        "Kontrol tamamlanmadan önce paylaşmaya devam etmek ister misiniz?"
    )
    check(copyright_dialog.COPYRIGHT_WARNING.search(screenshot_text) is not None, "ekrandaki modal metni birebir tanındı")
    check(copyright_dialog.COPYRIGHT_WARNING.search("Paylaşmaya devam edilsin mi?") is not None, "modal başlığı")
    check(copyright_dialog.COPYRIGHT_WARNING.search("Telif hakkı kontrolü eksik") is not None, "eksik telif kontrolü metni")
    check(copyright_dialog.IMMEDIATE_SHARE.fullmatch("Hemen paylaş") is not None, "exact Hemen paylaş")
    check(copyright_dialog.CANCEL.fullmatch("İptal") is not None, "İptal kardeş düğmesi")
    check(copyright_dialog.IMMEDIATE_SHARE.fullmatch("Paylaş") is None, "yanlış genel Paylaş eşleşmez")

    handler = inspect.getsource(copyright_dialog)
    check("[aria-modal=\"true\"]" in handler, "aria-modal fallback")
    check("[class*=\"modal\" i]" in handler, "class modal fallback")
    check("ancestor::*" in handler, "semantiksiz modal ancestor fallback")
    check("has_share and has_cancel" in handler, "Hemen paylaş + İptal ile container doğrulama")
    check("_click_immediate_share(container)" in handler, "doğrulanmış container içinde tıklama")
    check(web_uploader.confirm_publish_dialog.__module__ == "tiktok_login", "handler web uploader'a kuruldu")
    check(tiktok_login.handle_copyright_publish_dialog.__module__ == "tiktok_login", "handler delegasyonu")

    flow = inspect.getsource(web_uploader.prepare_upload)
    steps = ["button.click(", "confirm_publish_dialog(", "wait_for_publish_result("]
    positions = [flow.index(step) for step in steps]
    check(positions == sorted(positions), "ana Paylaş → Hemen paylaş → yayın sonucu")

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
    print("\nGERÇEK TELİF MODALI VE SIRALI YAYIN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
