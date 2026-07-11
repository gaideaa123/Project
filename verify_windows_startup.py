from __future__ import annotations

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
        "app.py", "app_tr.py", "proxy_publisher.py", "proxy_health.py",
        "network_identity.py", "network_identity_gui.py", "uniquizer_tab.py",
        "video_variants.py", "session_account_gui.py", "tiktok_login.py",
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
            checks = (
                (hasattr(window, "network_identity_page"), "Proxy Listesi oluşturulmadı"),
                (window.uniquizer_tab is not None, "Cold Open Uniquizer oluşturulmadı"),
                (hasattr(window, "session_accounts_page"), "Session ID Hesapları oluşturulmadı"),
                (hasattr(window, "session_add_button"), "Session ID ekleme düğmesi oluşturulmadı"),
            )
            for passed, message in checks:
                if not passed:
                    return fail(message)
        finally:
            window.close()
            app.processEvents()
    except Exception as exc:
        return fail(f"{type(exc).__name__}: {exc}")
    print("OK: app_tr, Proxy, Cold Open ve Session ID hesap yönetimi doğrulandı")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
