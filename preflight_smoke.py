from __future__ import annotations

import inspect
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import content_preflight
import preflight_hook


def check(value: bool, text: str) -> None:
    if not value:
        raise AssertionError(text)
    print("OK:", text)


def main() -> None:
    source = inspect.getsource(preflight_hook.install)
    check("content_preflight.validate" in source, "yayın öncesi preflight")
    check("content_preflight.record" in source, "başarılı yayın audit kaydı")
    check("if publish" in source, "taslak hazırlamada yanlış yayın kaydı yok")

    report = content_preflight.MediaReport(
        path="video.mp4", sha256="abc", duration=12.0, width=1080,
        height=1920, video_codec="h264", pixel_format="yuv420p",
        frame_rate=30.0, has_audio=False, audio_codec="", size_bytes=1234,
        warnings=("ses stream yok",),
    )
    check(report.has_audio is False, "sessiz video uyarıdır, hard fail değildir")

    uploader = MagicMock()
    uploader._signaldesk_preflight_installed = False
    request = MagicMock()
    request.profile = "captionai"
    request.video = Path("1.mp4")
    request.caption = "Caption"
    original = MagicMock(return_value=None)
    uploader.prepare_upload = original
    preflight_hook.install(uploader)
    with patch.object(content_preflight, "validate", return_value=report) as validate, patch.object(content_preflight, "record") as record:
        uploader.prepare_upload(request, publish=True)
        validate.assert_called_once_with("captionai", Path("1.mp4"), "Caption")
        record.assert_called_once_with("captionai", report, "published")
        check(True, "preflight ve audit gerçek wrapper'da")

    with tempfile.TemporaryDirectory() as temporary:
        audit = Path(temporary) / "audit.json"
        with patch.object(content_preflight, "AUDIT_FILE", audit), patch.object(content_preflight, "DATA_DIR", Path(temporary)):
            content_preflight.record("captionai", report)
            check(audit.is_file(), "atomik audit dosyası")
            check("captionai" in audit.read_text(encoding="utf-8"), "audit profil kaydı")

    print("\nPREFLIGHT VE AUDIT TESTLERİ GEÇTİ")


if __name__ == "__main__":
    main()
