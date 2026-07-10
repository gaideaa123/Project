from __future__ import annotations

import inspect
import os
import py_compile
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
    import video_variants
    from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QSpinBox

    check("output_dir" in inspect.signature(video_variants.create_variants).parameters, "seçilebilir output folder")
    chain = video_variants.visual_chain("0", 1, 1.02, 1, 1, 0, True)
    check("setpts=PTS-STARTPTS" in chain and "setsar=1" in chain, "cold-open motoru")

    qt = QApplication.instance() or QApplication([])
    with patch.object(app_tr.tiktok_login, "has_session", return_value=False), patch.object(app_tr.tiktok_login, "has_credentials", return_value=False):
        window = app_tr.TurkceAnaPencere()
        labels = [window.tabs.tabText(i) for i in range(window.tabs.count())]
        check("Varyasyonlara Ayır" in labels, "ayrı Varyasyonlara Ayır sekmesi")
        tab = window.uniquizer_tab
        check(isinstance(tab.input_video, QLineEdit), "input video alanı")
        check(isinstance(tab.output_folder, QLineEdit), "output folder alanı")
        check(isinstance(tab.variant_count, QSpinBox), "varyasyon adet alanı")
        check(tab.variant_count.minimum() == 1 and tab.variant_count.maximum() == 100, "1-100 adet")
        check(isinstance(tab.start_button, QPushButton), "tek tık uniquizer düğmesi")
        window.close()
    qt.quit()
    print("\nAYRI UNIQUIZER SEKME TESTLERİ GEÇTİ")


if __name__ == "__main__": main()
