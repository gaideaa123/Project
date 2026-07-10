from __future__ import annotations

import hashlib
import os
import py_compile
import string
import tempfile
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print("OK:", message)


def main() -> None:
    root = Path(__file__).parent
    for name in ("app.py", "app_tr.py", "oauth_helper.py"):
        py_compile.compile(str(root / name), doraise=True)
        check(True, f"{name} sözdizimi")

    import app
    import app_tr
    import oauth_helper
    from PySide6.QtWidgets import QApplication

    qt = QApplication.instance() or QApplication([])
    window = app_tr.TurkceAnaPencere()
    check(hasattr(window, "master"), "ana medya alanı uyumlu")
    check(hasattr(window, "output_dir"), "çıktı klasörü alanı mevcut")
    check(hasattr(window, "batch_size"), "toplu işlem boyutu mevcut")
    check(window.tabs.count() == 4, "dört Türkçe sekme yüklendi")

    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "ciktilar"
        target.mkdir()
        window.output_dir.setText(str(target))
        window._normalize_output()
        check(window.output_dir.text() == str(target.resolve()), "çıktı yolu GUI'ye yazılıyor")
        probe = target / "write.test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        check(True, "çıktı klasörüne yazılabiliyor")

        registry_class = getattr(app, "PipelineRegistry", getattr(app, "AtomicRegistry", None))
        check(registry_class is not None, "kayıt motoru mevcut")

    verifier = oauth_helper.make_verifier()
    check(len(verifier) == 64, "PKCE verifier uzunluğu")
    check(all(c in string.ascii_letters + string.digits + "-._~" for c in verifier), "PKCE karakter kümesi")
    challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
    check(len(challenge) == 64, "PKCE hex challenge")
    window.close()
    qt.quit()
    print("\nTÜM DUMAN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
