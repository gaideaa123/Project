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
        "copyright_policy.py", "video_variants.py", "uniquizer_tab.py",
    ):
        py_compile.compile(str(root / filename), doraise=True)
        check(True, f"{filename} sözdizimi")

    import app_tr
    import copyright_dialog
    import copyright_policy
    import tiktok_login
    import tiktok_overlays
    import web_uploader
    from PySide6.QtWidgets import QApplication, QSpinBox

    check(copyright_policy.is_first_profile_video(Path("1.mp4")), "1.mp4 ilk profil")
    for name in ("2.mp4", "3.mp4", "10.mp4", "1.mov", "video.mp4"):
        check(not copyright_policy.is_first_profile_video(Path(name)), f"{name} telif onayı almaz")

    install_source = inspect.getsource(tiktok_login.install)
    check("is_first_profile_video(request.video)" in install_source, "karar atanmış video numarasından alınır")
    check("first_profile_confirm if is_first else no_copyright_confirm" in install_source, "yalnız ilk profil handler seçimi")
    check("web_uploader.confirm_publish_dialog = previous_confirm" in install_source, "profil sonrası handler geri yüklenir")
    check("handle_copyright_publish_dialog" not in inspect.getsource(copyright_policy), "policy dialoga dokunmaz")
    check(copyright_dialog.IMMEDIATE_SHARE.fullmatch("Hemen paylaş") is not None, "ilk profil exact Hemen paylaş")

    check(tiktok_overlays.CLOSE.fullmatch("Kapat") is not None, "sonraki hesaplarda Kapat korunuyor")
    check(tiktok_overlays.GOT_IT.fullmatch("Anladım") is not None, "sonraki hesaplarda Anladım korunuyor")
    check(tiktok_overlays.EXCLUDED_TEXT.search("Telif hakkı kontrolü eksik") is not None, "onboarding telif dialoguna dokunmaz")

    flow = inspect.getsource(web_uploader.prepare_upload)
    steps = ["button.click(", "confirm_publish_dialog(", "wait_for_publish_result("]
    positions = [flow.index(step) for step in steps]
    check(positions == sorted(positions), "ana Paylaş → koşullu telif onayı → sonuç")

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
                check(window.pending_assignments == expected, "1.mp4 ilk, 2.mp4 ikinci, 3.mp4 üçüncü profil")
                start.assert_called_once_with(expected)
        window.close()
    qt.quit()
    print("\nİLK PROFİL TELİF POLİTİKASI VE SIRALI YAYIN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
