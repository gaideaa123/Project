from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")


def main() -> None:
    from PySide6.QtWidgets import QApplication, QGridLayout

    # sitecustomize may be unavailable in zip downloads or some Windows venvs.
    # Remove its optional patch so this test proves app_tr's guaranteed import
    # path installs compatibility by itself.
    if hasattr(QGridLayout, "insertLayout"):
        delattr(QGridLayout, "insertLayout")

    import app_tr

    assert hasattr(QGridLayout, "insertLayout"), "Doğrudan grid uyumluluğu kurulmadı"
    app = QApplication.instance() or QApplication([])
    window = app_tr.TurkceAnaPencere()
    assert hasattr(window, "output_dir"), "Türkçe pencere çıktı alanı olmadan açıldı"
    assert hasattr(window, "network_identity_page"), "Proxy sekmesi oluşturulmadı"
    window.close()
    app.processEvents()
    print("APP_TR DOĞRUDAN BAŞLANGIÇ TESTİ GEÇTİ")


if __name__ == "__main__":
    main()
