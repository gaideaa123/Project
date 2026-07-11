from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")


def main() -> None:
    from PySide6.QtWidgets import QApplication, QGridLayout

    if hasattr(QGridLayout, "insertLayout"):
        delattr(QGridLayout, "insertLayout")

    import app_tr

    assert hasattr(QGridLayout, "insertLayout"), "Doğrudan grid uyumluluğu kurulmadı"
    app = QApplication.instance() or QApplication([])
    window = app_tr.TurkceAnaPencere()
    assert hasattr(window, "output_dir"), "Türkçe pencere çıktı alanı olmadan açıldı"
    assert hasattr(window, "network_identity_page"), "Proxy sekmesi oluşturulmadı"
    assert window.uniquizer_tab is not None, "Cold Open Uniquizer oluşturulmadı"
    assert window.tabs.indexOf(window.uniquizer_tab) >= 0, "Cold Open Uniquizer sekmesi eklenmedi"
    window.close()
    app.processEvents()
    print("APP_TR PROXY + COLD OPEN BAŞLANGIÇ TESTİ GEÇTİ")


if __name__ == "__main__":
    main()
