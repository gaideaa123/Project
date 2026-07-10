from __future__ import annotations

import os
import py_compile
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def check(value: bool, text: str) -> None:
    if not value: raise AssertionError(text)
    print("OK:", text)


def main() -> None:
    root = Path(__file__).parent
    for filename in ("app.py", "app_tr.py", "oauth_helper.py", "web_uploader.py", "tiktok_login.py", "video_variants.py", "uniquizer_tab.py"):
        py_compile.compile(str(root / filename), doraise=True); check(True, f"{filename} sözdizimi")

    import app_tr
    from PySide6.QtWidgets import QApplication, QSpinBox

    qt = QApplication.instance() or QApplication([])
    with patch.object(app_tr.tiktok_login, "has_session", return_value=False), patch.object(app_tr.tiktok_login, "has_credentials", return_value=False):
        window = app_tr.TurkceAnaPencere()
        labels = [window.tabs.tabText(i) for i in range(window.tabs.count())]
        check("Varyasyonlara Ayır" in labels and "Azure + Web Yükleyici" in labels, "iki ayrı sekme")
        spins = window.azure_web_page.findChildren(QSpinBox)
        check(len(spins) == 0, "Azure + Web sekmesinde varyasyon sayısı kaldırıldı")
        check(window.uniquizer_tab.variant_count.minimum() == 1, "varyasyon sayısı yalnız üretici sekmesinde")

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            files = []
            for index in range(1, 5):
                file = folder / f"{index}.mp4"; file.write_bytes(b"video"); files.append(str(file))
            with patch.object(window, "account_names", return_value=["captionai", "Emre", "Berlin"]), patch.object(window, "refresh_web_profiles"), patch.object(window, "save_azure", return_value=True), patch.object(window, "start_publish") as start:
                window.distribute_uniquizer_outputs(files)
                expected = [("captionai", Path(files[0]).resolve()), ("Emre", Path(files[1]).resolve()), ("Berlin", Path(files[2]).resolve())]
                check(window.pending_assignments == expected, "1.mp4→captionai, 2.mp4→Emre sıralı eşleşme")
                start.assert_called_once_with(expected)
                check(True, "üretim sonrası web yayın akışı otomatik başladı")

            with patch.object(window, "account_names", return_value=["A", "B", "C"]), patch.object(app_tr.QMessageBox, "critical") as error:
                window.distribute_uniquizer_outputs(files[:2])
                check(error.called, "profil sayısından az varyasyon engellendi")
        window.close()
    qt.quit()
    print("\nDAĞITIM VE WEB YAYIN TESTLERİ GEÇTİ")


if __name__ == "__main__": main()
