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
        "tiktok_login.py", "tiktok_overlays.py", "copyright_dialog.py",
        "video_variants.py", "uniquizer_tab.py",
    ):
        py_compile.compile(str(root / filename), doraise=True)
        check(True, f"{filename} sözdizimi")

    import app_tr
    import copyright_dialog
    import tiktok_login
    import tiktok_overlays
    import web_uploader
    from PySide6.QtWidgets import QApplication, QSpinBox

    check(tiktok_overlays.COOKIE_ALLOW.fullmatch("Çerezlere izin ver") is not None, "çerez izni")
    check(tiktok_overlays.COOKIE_ALLOW.fullmatch("Allow all cookies") is not None, "İngilizce çerez izni")
    check(tiktok_overlays.CLOSE.fullmatch("Kapat") is not None, "exact Kapat")
    for text in ("Anladım", "Tamam", "Got it", "I understand"):
        check(tiktok_overlays.GOT_IT.fullmatch(text) is not None, f"bilgilendirme düğmesi: {text}")
    check(tiktok_overlays.EXCLUDED_TEXT.search("Telif hakkı kontrolü eksik") is not None, "telif modalı onboarding temizleyiciden hariç")
    check(tiktok_overlays.EXCLUDED_TEXT.search("Paylaşmaya devam edilsin mi") is not None, "paylaş modalı onboarding temizleyiciden hariç")

    clear_source = inspect.getsource(tiktok_overlays.clear_new_account_overlays)
    cookie_pos = clear_source.index('_click_cookie')
    close_pos = clear_source.index('_click_close')
    got_pos = clear_source.index('_click_got_it')
    check(cookie_pos < close_pos < got_pos, "çerez → Kapat → Anladım sırası")
    check('or _click_got_it' in clear_source, "tekrarlayan Kapat/Anladım döngüsü")
    check('quiet_seconds' in clear_source, "tüm Anladım pencereleri bitene kadar bekleme")

    install_source = inspect.getsource(tiktok_login.install)
    check("clear_new_account_overlays" in install_source, "overlay yöneticisi uploader'a bağlı")
    check("web_uploader.dismiss_pre_caption_notice = dismiss_pre_caption_notice" in install_source, "caption öncesi ikinci temizlik bağlı")
    check(web_uploader.dismiss_pre_caption_notice.__module__ == "tiktok_login", "gerçek uploader overlay wrapper kullanıyor")
    check(copyright_dialog.COPYRIGHT_WARNING.search("Telif hakkı kontrolü eksik") is not None, "telif handler korunuyor")

    flow = inspect.getsource(web_uploader.prepare_upload)
    steps = ["button.click(", "confirm_publish_dialog(", "wait_for_publish_result("]
    positions = [flow.index(step) for step in steps]
    check(positions == sorted(positions), "Paylaş → Hemen paylaş → sonuç sırası korunuyor")

    qt = QApplication.instance() or QApplication([])
    with patch.object(app_tr.tiktok_login, "has_session", return_value=False), patch.object(app_tr.tiktok_login, "has_credentials", return_value=False):
        window = app_tr.TurkceAnaPencere()
        check(len(window.azure_web_page.findChildren(QSpinBox)) == 0, "Azure + Web varyasyon sayısı yok")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); files = []
            for index in range(1, 3):
                file = folder / f"{index}.mp4"; file.write_bytes(b"video"); files.append(str(file))
            with patch.object(window, "account_names", return_value=["captionai", "Emre"]), patch.object(window, "refresh_web_profiles"), patch.object(window, "save_azure", return_value=True), patch.object(window, "start_publish") as start:
                window.distribute_uniquizer_outputs(files)
                expected = [("captionai", Path(files[0]).resolve()), ("Emre", Path(files[1]).resolve())]
                check(window.pending_assignments == expected, "profil-video sırası korundu")
                start.assert_called_once_with(expected)
        window.close()
    qt.quit()
    print("\nYENİ HESAP OVERLAY VE SIRALI YAYIN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
