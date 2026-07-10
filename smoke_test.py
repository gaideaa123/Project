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
    for name in ("app.py", "app_tr.py", "run_tr.py", "oauth_helper.py"):
        py_compile.compile(str(root / name), doraise=True)
        check(True, f"{name} sözdizimi")

    import app
    import oauth_helper
    import run_tr
    from PySide6.QtWidgets import QApplication

    qt = QApplication.instance() or QApplication([])
    window = run_tr.SignalDeskTurkce()
    window._uyumluluk_eslemelerini_kur()
    check(hasattr(window, "output_dir"), "çıktı klasörü alanı bulundu ve eşlendi")
    check(hasattr(window, "master"), "ana medya alanı bulundu ve eşlendi")
    check(hasattr(window, "batch_size"), "toplu işlem sayacı bulundu ve eşlendi")
    check(window.tabs.count() >= 4, "Türkçe sekmeler yüklendi")

    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "ciktilar"
        target.mkdir(parents=True)
        window.output_dir.setText(str(target))
        check(window.output_dir.text() == str(target), "çıktı klasörü yolu GUI alanına yazılıyor")
        probe = target / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        check(True, "çıktı klasörüne yazılabiliyor")

        registry = app.PipelineRegistry(Path(temporary) / "pipeline_registry.json")
        account = registry.add_account("Test Profil", "TikTok")
        video = Path(temporary) / "test.mp4"
        video.write_bytes(b"test")
        first = app.now_utc() + timedelta(hours=24)
        registry.add_job(account["id"], str(video), "test", first, False)
        try:
            registry.add_job(account["id"], str(video), "test 2", first + timedelta(hours=1), False)
            raise AssertionError("23 saat koruması devreye girmedi")
        except app.RegistryError:
            check(True, "23 saat kuyruk koruması çalışıyor")

    verifier = oauth_helper.make_verifier()
    check(len(verifier) == 64, "PKCE verifier uzunluğu")
    check(all(c in string.ascii_letters + string.digits + "-._~" for c in verifier), "PKCE karakter kümesi")
    challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
    check(len(challenge) == 64, "PKCE hex challenge")
    check(len(app.RenditionEngine.RESOLUTIONS) == 4, "H.264 çıktı profilleri")
    window.close()
    qt.quit()
    print("\nTÜM DUMAN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
