from __future__ import annotations

import hashlib
import os
import py_compile
import string
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def check(value: bool, text: str) -> None:
    if not value:
        raise AssertionError(text)
    print("OK:", text)


def main() -> None:
    root = Path(__file__).parent
    for filename in ("app.py", "app_tr.py", "oauth_helper.py"):
        py_compile.compile(str(root / filename), doraise=True)
        check(True, f"{filename} sözdizimi")

    import app_tr
    import oauth_helper
    from PySide6.QtWidgets import QApplication, QLineEdit, QProgressBar, QSpinBox

    qt = QApplication.instance() or QApplication([])
    window = app_tr.TurkceAnaPencere()
    check(isinstance(window.master, QLineEdit), "ana medya alanı bulundu")
    check(isinstance(window.output_dir, QLineEdit), "çıktı klasörü alanı bulundu")
    check(isinstance(window.batch_size, QSpinBox), "çıktı sayısı alanı bulundu")
    check(isinstance(window.progress, QProgressBar), "ilerleme çubuğu bulundu")
    check(window.tabs.count() == 4, "dört sekme yüklendi")

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

    verifier = oauth_helper.make_verifier()
    check(len(verifier) == 64, "PKCE verifier uzunluğu")
    check(all(c in string.ascii_letters + string.digits + "-._~" for c in verifier), "PKCE karakter kümesi")
    check(len(hashlib.sha256(verifier.encode("ascii")).hexdigest()) == 64, "PKCE hex challenge")
    window.close()
    qt.quit()
    print("\nTÜM DUMAN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
