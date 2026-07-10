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
    from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QProgressBar, QSpinBox

    qt = QApplication.instance() or QApplication([])
    window = app_tr.TurkceAnaPencere()
    check(isinstance(window.master, QLineEdit), "ana medya alanı")
    check(isinstance(window.hook_dir, QLineEdit), "hook klasörü alanı")
    check(isinstance(window.broll_dir, QLineEdit), "B-roll klasörü alanı")
    check(isinstance(window.output_dir, QLineEdit), "çıktı klasörü alanı")
    check(isinstance(window.cta_texts, QPlainTextEdit), "CTA listesi")
    check(isinstance(window.batch_size, QSpinBox), "varyant sayısı")
    check(isinstance(window.progress, QProgressBar), "ilerleme çubuğu")
    check(window.tabs.count() == 4, "dört sekme")

    with tempfile.TemporaryDirectory() as temporary:
        root_temp = Path(temporary)
        for name in ("hooks", "broll", "output"):
            (root_temp / name).mkdir()
        check((root_temp / "output").is_dir(), "yaratıcı klasör yapısı")
        state = window.registry.snapshot()
        check(isinstance(state.get("accounts", []), list), "kayıt motoru")

    verifier = oauth_helper.make_verifier()
    check(len(verifier) == 64, "PKCE verifier")
    check(all(c in string.ascii_letters + string.digits + "-._~" for c in verifier), "PKCE karakterleri")
    check(len(hashlib.sha256(verifier.encode("ascii")).hexdigest()) == 64, "PKCE challenge")
    window.close()
    qt.quit()
    print("\nTÜM DUMAN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
