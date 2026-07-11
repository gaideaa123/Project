from __future__ import annotations

"""Technical preflight and audit for legitimate TikTok publishing.

This module does not attempt to evade recommendation or automation detection.
It catches concrete causes of failed/zero-distribution posts: invalid streams,
very short media, unsupported codecs, missing audio, empty captions, and exact
re-uploads of the same file.
"""

import hashlib
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from platformdirs import user_data_dir

UTC = timezone.utc
DATA_DIR = Path(user_data_dir("signaldesk-studio", "SignalDesk"))
AUDIT_FILE = DATA_DIR / "publication_audit.json"


class PreflightError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaReport:
    path: str
    sha256: str
    duration: float
    width: int
    height: int
    video_codec: str
    pixel_format: str
    frame_rate: float
    has_audio: bool
    audio_codec: str
    size_bytes: int


def _rate(value: str) -> float:
    try:
        numerator, denominator = value.split("/", 1)
        return float(numerator) / float(denominator or 1)
    except (AttributeError, ValueError, ZeroDivisionError):
        return 0.0


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_media(path: Path) -> MediaReport:
    path = path.expanduser().resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise PreflightError(f"Video bulunamadı veya boş: {path}")
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise PreflightError("FFprobe PATH üzerinde bulunamadı")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,codec_name,pix_fmt,width,height,avg_frame_rate",
         "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode:
        raise PreflightError(result.stderr.strip() or "FFprobe videoyu okuyamadı")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PreflightError("FFprobe geçersiz JSON döndürdü") from exc
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not video:
        raise PreflightError("Dosyada video stream bulunamadı")
    report = MediaReport(
        path=str(path), sha256=file_sha256(path),
        duration=float(data.get("format", {}).get("duration") or 0),
        width=int(video.get("width") or 0), height=int(video.get("height") or 0),
        video_codec=str(video.get("codec_name") or ""),
        pixel_format=str(video.get("pix_fmt") or ""),
        frame_rate=_rate(str(video.get("avg_frame_rate") or "0/1")),
        has_audio=audio is not None,
        audio_codec=str((audio or {}).get("codec_name") or ""),
        size_bytes=path.stat().st_size,
    )
    errors = []
    if report.duration < 1.0:
        errors.append("video 1 saniyeden kısa")
    if report.width < 720 or report.height < 720:
        errors.append("çözünürlük 720 pikselin altında")
    if report.video_codec not in {"h264", "hevc"}:
        errors.append(f"video codec destek dışı: {report.video_codec}")
    if report.pixel_format not in {"yuv420p", "yuvj420p"}:
        errors.append(f"pixel format riskli: {report.pixel_format}")
    if not 23.0 <= report.frame_rate <= 61.0:
        errors.append(f"frame rate riskli: {report.frame_rate:.2f}")
    if not report.has_audio:
        errors.append("ses stream yok")
    elif report.audio_codec != "aac":
        errors.append(f"audio codec AAC değil: {report.audio_codec}")
    if errors:
        raise PreflightError("Medya preflight başarısız: " + "; ".join(errors))
    return report


def _load_audit() -> list[dict]:
    try:
        data = json.loads(AUDIT_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def validate(profile: str, video: Path, caption: str) -> MediaReport:
    if not profile.strip():
        raise PreflightError("Profil adı boş")
    caption = caption.strip()
    if not caption or len(caption) > 2200:
        raise PreflightError("Caption boş veya 2200 karakterden uzun")
    report = inspect_media(video)
    cutoff = datetime.now(UTC) - timedelta(days=30)
    for item in _load_audit():
        try:
            created = datetime.fromisoformat(str(item.get("created_at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if created >= cutoff and item.get("sha256") == report.sha256:
            raise PreflightError(
                "Aynı video dosyası son 30 gün içinde zaten yayınlanmış; exact tekrar gönderim durduruldu"
            )
    return report


def record(profile: str, report: MediaReport, result: str = "published") -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    items = _load_audit()
    items.append({
        **asdict(report), "profile": profile, "result": result,
        "created_at": datetime.now(UTC).isoformat(),
    })
    temporary = AUDIT_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(items[-1000:], ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(AUDIT_FILE)
