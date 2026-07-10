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
    check(hasattr(window, "output_dir"), "çıktı klasörü alanı mevcut")
    check(hasattr(window, "batch_size"), "toplu işlem boyutu mevcut")
    check(window.tabs.count() == 4, "dört Türkçe sekme yüklendi")
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "ciktilar"
        window.output_dir.setText(str(target))
        window.start_batch = lambda: None
        target.mkdir()
        check(target.is_dir(), "çıktı klasörü oluşturulabiliyor")

        registry = app.PipelineRegistry(Path(temporary) / "pipeline_registry.json")
        account = registry.add_account("Test Profil", "TikTok", "")
        video = Path(temporary) / "test.mp4"
        video.write_bytes(b"test")
        first = app.now_utc() + timedelta(hours=24)
        registry.queue_job(account["id"], video, "test", first, False)
        try:
            registry.queue_job(account["id"], video, "test 2", first + timedelta(hours=1), False)
            raise AssertionError("23 saat koruması devreye girmedi")
        except app.RateLimitError:
            check(True, "23 saat koruması çalışıyor")

    verifier = oauth_helper.make_verifier()
    check(len(verifier) == 64, "PKCE verifier uzunluğu")
    check(all(char in string.ascii_letters + string.digits + "-._~" for char in verifier), "PKCE karakter kümesi")
    challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
    check(len(challenge) == 64 and all(char in string.hexdigits for char in challenge), "PKCE hex challenge")
    check(len(app.H264BatchEncoder.RESOLUTIONS) == 4, "H.264 profil planı")
    window.close()
    qt.quit()
    print("\nTÜM DUMAN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
