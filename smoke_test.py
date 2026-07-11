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
        "content_preflight.py", "preflight_hook.py", "video_variants.py",
        "uniquizer_tab.py",
    ):
        py_compile.compile(str(root / filename), doraise=True)
        check(True, f"{filename} sözdizimi")

    import app_tr
    import copyright_dialog
    import tiktok_login
    import tiktok_overlays
    import web_uploader
    from PySide6.QtWidgets import QApplication, QSpinBox

    check(tiktok_overlays.CONTENT_CHECK_TEXT.search("İçerik kontrolü") is not None, "içerik kontrolü modalı")
    for label in ("Aç", "Etkinleştir", "İçerik kontrolünü aç", "Turn on", "Enable"):
        check(tiktok_overlays.ENABLE_CONTENT_CHECK.fullmatch(label) is not None, f"kontrol açma düğmesi: {label}")
    check(tiktok_overlays.ENABLE_CONTENT_CHECK.fullmatch("Kapat") is None, "Kapat hiçbir zaman Aç olarak eşleşmez")

    overlay_source = inspect.getsource(tiktok_overlays)
    clear_source = inspect.getsource(tiktok_overlays.clear_new_account_overlays)
    check("_click_close" not in overlay_source, "Kapat tıklama kodu tamamen kaldırıldı")
    check("_enable_content_check" in clear_source, "içerik kontrolü Aç akışına bağlı")
    check(clear_source.index("_click_cookie") < clear_source.index("_enable_content_check") < clear_source.index("_click_got_it"), "çerez → Aç → Anladım sırası")
    check("CONTENT_CHECK_TEXT.search(text)" in inspect.getsource(tiktok_overlays._enable_content_check), "Aç yalnız içerik kontrolü container'ında")
    check("PUBLISH_TEXT.search(text)" in inspect.getsource(tiktok_overlays._enable_content_check), "paylaş/telif dialogu onboarding Aç akışından hariç")

    login_source = inspect.getsource(tiktok_login.install)
    check("confirm_for_every_profile" in login_source, "telif kontrolü tüm profillerde")
    check("is_first_profile_video" not in login_source, "1.mp4 özel kısıtı kaldırıldı")
    check("no_copyright_confirm" not in login_source, "sonraki profillerde telif handler kapatılmıyor")
    check("web_uploader.confirm_publish_dialog = confirm_for_every_profile" in login_source, "global ve profil çağrısı telif handler'a bağlı")
    check("previous_confirm" in login_source, "wrapper profil sonrası güvenli geri yüklenir")

    copyright_source = inspect.getsource(copyright_dialog.handle)
    check(copyright_dialog.IMMEDIATE_SHARE.fullmatch("Hemen paylaş") is not None, "Hemen paylaş uyarısı tanınır")
    check(copyright_dialog.CANCEL.fullmatch("İptal") is not None, "İptal düğmesi exact tanınır")
    check("_click_exact_cancel" in copyright_source, "eksik kontrolde İptal tıklanır")
    check("_click_immediate_share" not in inspect.getsource(copyright_dialog), "eksik telif kontrolü zorla geçilmez")
    check("CopyrightDialogError" in copyright_source, "eksik kontrolden sonra yayın fail-closed durur")

    flow = inspect.getsource(web_uploader.prepare_upload)
    steps = ["button.click(", "confirm_publish_dialog(", "wait_for_publish_result("]
    positions = [flow.index(step) for step in steps]
    check(positions == sorted(positions), "Paylaş → telif kontrol kapısı → doğrulanmış sonuç")

    qt = QApplication.instance() or QApplication([])
    with patch.object(app_tr.tiktok_login, "has_session", return_value=False), patch.object(app_tr.tiktok_login, "has_credentials", return_value=False):
        window = app_tr.TurkceAnaPencere()
        check(len(window.azure_web_page.findChildren(QSpinBox)) == 0, "Azure + Web varyasyon sayısı yok")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            files = []
            for index in range(1, 4):
                file = folder / f"{index}.mp4"
                file.write_bytes(b"video")
                files.append(str(file))
            with patch.object(window, "account_names", return_value=["captionai", "Emre", "Berlin"]), patch.object(window, "refresh_web_profiles"), patch.object(window, "save_azure", return_value=True), patch.object(window, "start_publish") as start:
                window.distribute_uniquizer_outputs(files)
                expected = [
                    ("captionai", Path(files[0]).resolve()),
                    ("Emre", Path(files[1]).resolve()),
                    ("Berlin", Path(files[2]).resolve()),
                ]
                check(window.pending_assignments == expected, "profil-video sırası korunuyor")
                start.assert_called_once_with(expected)
        window.close()
    qt.quit()
    print("\nİÇERİK KONTROLÜ FAIL-CLOSED VE SIRALI YAYIN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
