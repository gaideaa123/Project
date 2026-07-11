from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")


def main() -> None:
    import sitecustomize
    from PySide6.QtWidgets import QApplication, QGridLayout, QHBoxLayout, QWidget

    app = QApplication.instance() or QApplication([])
    host = QWidget()
    grid = QGridLayout(host)
    grid.insertLayout(0, QHBoxLayout())
    assert grid.count() == 1, "QGridLayout uyumluluk satırı eklenemedi"

    import app_tr

    window = app_tr.TurkceAnaPencere()
    assert hasattr(window, "output_dir"), "Türkçe pencere çıktı alanı olmadan açıldı"
    assert hasattr(window, "network_identity_page"), "Proxy sekmesi oluşturulmadı"
    window.close()
    app.processEvents()
    print("APP_TR LAYOUT UYUMLULUK TESTİ GEÇTİ")


if __name__ == "__main__":
    main()
