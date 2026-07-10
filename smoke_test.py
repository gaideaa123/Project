from __future__ import annotations

import os
import py_compile
import tempfile
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def check(value: bool, text: str) -> None:
    if not value:
        raise AssertionError(text)
    print("OK:", text)


def main() -> None:
    root = Path(__file__).parent
    for filename in ("app.py", "app_tr.py", "oauth_helper.py", "web_uploader.py"):
        py_compile.compile(str(root / filename), doraise=True)
        check(True, f"{filename} sözdizimi")

    import app
    import web_uploader

    check(web_uploader.safe_profile_name(" Marka Türkiye ") == "Marka-T-rkiye", "güvenli profil adı")
    try:
        web_uploader.safe_profile_name("!!!")
    except web_uploader.UploadError:
        check(True, "geçersiz profil reddi")
    else:
        raise AssertionError("geçersiz profil reddedilmedi")

    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        video = folder / "video.mp4"
        video.write_bytes(b"not-empty")
        request = web_uploader.UploadRequest("test", video, "caption")
        request.validate()
        check(True, "web yükleme isteği doğrulama")

        registry = app.AtomicRegistry(folder / "state.json")
        account = registry.add_account("Test")
        first = registry.add_job(account["id"], str(video), "bir", app.utc_now(), "SELF_ONLY")
        check(first["status"] == "queued", "iş kuyruğu")
        claimed, _ = registry.claim_job(first["id"])
        check(claimed["status"] == "running", "atomik iş sahiplenme")

        state = registry.snapshot()
        second = dict(first)
        second.update(id="second", status="queued", run_at=app.iso(app.utc_now() - timedelta(seconds=1)))
        state["jobs"].append(second)
        registry._atomic_write(state)
        try:
            registry.claim_job("second")
        except app.StateError:
            check(True, "aynı profil eşzamanlı yayın engeli")
        else:
            raise AssertionError("eşzamanlı yayın engellenmedi")

        lock = app.ProcessFileLock(folder / "test.lock", timeout=0.2)
        with lock:
            check(not app.ProcessFileLock(folder / "test.lock", timeout=0.1).acquire(), "süreçler arası kilit")

    print("\nTÜM DUMAN TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
