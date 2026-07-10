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
        "tiktok_login.py", "video_variants.py", "uniquizer_tab.py",
    ):
        py_compile.compile(str(root / filename), doraise=True)
        check(True, f"{filename} sözdizimi")

    import app_tr
    import web_uploader
    from PySide6.QtWidgets import QApplication, QSpinBox

    flow = inspect.getsource(web_uploader.prepare_upload)
    ordered_steps = [
        "upload_file(",
        "dismiss_pre_caption_notice(",
        "fill_caption(",
        "wait_for_upload_complete(",
        "button.click(",
        "wait_for_publish_result(",
    ]
    positions = [flow.index(step) for step in ordered_steps]
    check(positions == sorted(positions), "upload → Anladım → caption → tamamlanma → Paylaş → sonuç sırası")
    check("approval()" not in flow, "profil başına eski onay beklemesi kaldırıldı")
    check(web_uploader.NOTICE_BUTTON.fullmatch("Anladım") is not None, "Anladım düğmesi")
    check(web_uploader.NOTICE_BUTTON.fullmatch("Got it") is not None, "Got it düğmesi")
    check(web_uploader.PUBLISH_BUTTON.fullmatch("Paylaş") is not None, "Paylaş düğmesi")

    # Upload completion must be stable, not a single enabled-button snapshot.
    wait_source = inspect.getsource(web_uploader.wait_for_upload_complete)
    check("stable_checks >= 3" in wait_source, "üç ardışık upload-complete doğrulaması")
    check("upload_busy(page)" in wait_source, "aktif upload göstergesi kontrolü")

    # A complete aria progress bar is not treated as busy.
    page = MagicMock()
    body = MagicMock(); body.inner_text.return_value = "Video uploaded"
    bars = MagicMock(); bars.count.return_value = 1
    bar = MagicMock(); bar.is_visible.return_value = True; bar.get_attribute.return_value = "100"
    bars.nth.return_value = bar
    page.locator.side_effect = lambda selector: body if selector == "body" else bars
    check(web_uploader.upload_busy(page) is False, "%100 upload göstergesi tamamlandı")
    bar.get_attribute.return_value = "72"
    check(web_uploader.upload_busy(page) is True, "%72 upload göstergesi bekleniyor")

    qt = QApplication.instance() or QApplication([])
    with patch.object(app_tr.tiktok_login, "has_session", return_value=False), patch.object(app_tr.tiktok_login, "has_credentials", return_value=False):
        window = app_tr.TurkceAnaPencere()
        spins = window.azure_web_page.findChildren(QSpinBox)
        check(len(spins) == 0, "Azure + Web sekmesinde varyasyon sayısı yok")

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            files = []
            for index in range(1, 4):
                file = folder / f"{index}.mp4"
                file.write_bytes(b"video")
                files.append(str(file))
            with patch.object(window, "account_names", return_value=["captionai", "Emre"]), patch.object(window, "refresh_web_profiles"), patch.object(window, "save_azure", return_value=True), patch.object(window, "start_publish") as start:
                window.distribute_uniquizer_outputs(files)
                expected = [
                    ("captionai", Path(files[0]).resolve()),
                    ("Emre", Path(files[1]).resolve()),
                ]
                check(window.pending_assignments == expected, "profil-video sırası korundu")
                start.assert_called_once_with(expected)
                check(True, "üretim sonrası sıralı worker başlatıldı")
        window.close()
    qt.quit()
    print("\nTIKTOK MODAL, UPLOAD VE SIRALI YAYIN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
