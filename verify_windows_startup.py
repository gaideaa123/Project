from __future__ import annotations

"""Windows-friendly preflight that proves app_tr can construct its real window."""

import os
import py_compile
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")


def fail(message: str) -> int:
    print(f"HATA: {message}", file=sys.stderr)
    return 1


def main() -> int:
    root = Path(__file__).resolve().parent
    required = (
        "app.py",
        "app_tr.py",
        "proxy_publisher.py",
        "proxy_health.py",
        "network_identity.py",
        "network_identity_gui.py",
    )
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        return fail("Eksik dosyalar: " + ", ".join(missing))

    try:
        for name in required:
            py_compile.compile(str(root / name), doraise=True)

        from PySide6.QtWidgets import QApplication, QGridLayout
        import app_tr

        if not hasattr(QGridLayout, "insertLayout"):
            return fail("QGridLayout uyumluluk katmanı kurulmadı")

        app = QApplication.instance() or QApplication([])
        window = app_tr.TurkceAnaPencere()
        try:
            if not hasattr(window, "network_identity_page"):
                return fail("Proxy Listesi sekmesi oluşturulmadı")
            if not hasattr(window, "output_dir"):
                return fail("Çıktı klasörü alanı oluşturulmadı")
            if window.tabs.indexOf(window.network_identity_page) < 0:
                return fail("Proxy Listesi sekmesi pencereye eklenmedi")
        finally:
            window.close()
            app.processEvents()
    except Exception as exc:
        return fail(f"{type(exc).__name__}: {exc}")

    print("OK: app_tr gerçek pencere başlangıcı ve Proxy Listesi doğrulandı")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
