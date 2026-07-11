from __future__ import annotations

"""Technical media quality and cross-profile originality audit."""

import hashlib
import json
import re
import shutil
import subprocess
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from platformdirs import user_data_dir

UTC = timezone.utc
DATA_DIR = Path(user_data_dir("signaldesk-studio", "SignalDesk"))
AUDIT_FILE = DATA_DIR / "publication_audit.json"
_LOCK = threading.RLock()


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
    warnings: tuple[str, ...]


def _rate(value: str) -> float:
    try:
        numerator, denominator = value.split("/", 1)
        return float(numerator) / float(denominator or 1)
    except (AttributeError, ValueError, ZeroDivisionError):
        return 0.0


def _digest_text(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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
         "-of", "json", str(path)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
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
    duration = float(data.get("format", {}).get("duration") or 0)
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    codec, pixel = str(video.get("codec_name") or ""), str(video.get("pix_fmt") or "")
    fps = _rate(str(video.get("avg_frame_rate") or "0/1"))
    errors: list[str] = []
    warnings: list[str] = []
    if duration < 1.0:
        errors.append("video 1 saniyeden kısa")
    if min(width, height) < 720:
        errors.append("kısa kenar 720 pikselin altında")
    if codec not in {"h264", "hevc"}:
        errors.append(f"video codec destek dışı: {codec}")
    if pixel not in {"yuv420p", "yuvj420p"}:
        errors.append(f"pixel format riskli: {pixel}")
    if not 23.0 <= fps <= 61.0:
        errors.append(f"frame rate riskli: {fps:.2f}")
    if audio is None:
        warnings.append("ses stream yok")
    elif str(audio.get("codec_name") or "") != "aac":
        warnings.append("audio codec AAC değil")
    if errors:
        raise PreflightError("Medya preflight başarısız: " + "; ".join(errors))
    return MediaReport(
        str(path), file_sha256(path), duration, width, height, codec, pixel, fps,
        audio is not None, str((audio or {}).get("codec_name") or ""),
        path.stat().st_size, tuple(warnings),
    )


def _load_unlocked() -> list[dict]:
    try:
        data = json.loads(AUDIT_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def validate(profile: str, video: Path, caption: str) -> MediaReport:
    if not profile.strip():
        raise PreflightError("Profil adı boş")
    if not caption.strip() or len(caption.strip()) > 2200:
        raise PreflightError("Caption boş veya 2200 karakterden uzun")
    report = inspect_media(video)
    caption_hash = _digest_text(caption)
    now = datetime.now(UTC)
    with _LOCK:
        items = _load_unlocked()
    for item in items:
        try:
            created = datetime.fromisoformat(str(item.get("created_at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if created >= now - timedelta(days=30) and item.get("sha256") == report.sha256:
            raise PreflightError(
                "Bu dosyanın aynısı son 30 gün içinde bir profilde yayınlanmış. "
                "Hesaplar arası exact tekrar engellendi."
            )
        if created >= now - timedelta(days=7) and item.get("caption_sha256") == caption_hash:
            raise PreflightError(
                "Aynı caption son 7 gün içinde kullanılmış. Azure'dan yeni bir caption üretip yeniden deneyin."
            )
    return report


def record(profile: str, report: MediaReport, result: str = "published", caption: str = "") -> None:
    with _LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        items = _load_unlocked()
        payload = asdict(report)
        payload["warnings"] = list(report.warnings)
        items.append({
            **payload,
            "profile": profile,
            "result": result,
            "caption_sha256": _digest_text(caption) if caption else "",
            "created_at": datetime.now(UTC).isoformat(),
        })
        temporary = AUDIT_FILE.with_suffix(AUDIT_FILE.suffix + ".tmp")
        temporary.write_text(
            json.dumps(items[-1000:], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(AUDIT_FILE)
