from __future__ import annotations

"""Create a user-selected number of standards-compliant delivery variants."""

import json
import math
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

Progress = Callable[[int, str], None]


class VariantError(RuntimeError):
    pass


def _probe_audio(ffprobe: str, source: Path) -> bool:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=index", "-of", "json", str(source)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode:
        raise VariantError(result.stderr.strip() or "FFprobe medya dosyasını okuyamadı")
    try:
        return bool(json.loads(result.stdout).get("streams"))
    except json.JSONDecodeError as exc:
        raise VariantError("FFprobe geçersiz sonuç döndürdü") from exc


def variant_parameters(index: int) -> tuple[float, float, float, float, int]:
    """Deterministic, bounded encode settings for variant index 1..N."""
    if index < 1:
        raise VariantError("Varyasyon numarası 1 veya daha büyük olmalı")
    phase = index - 1
    zoom = 1.0 + (phase % 13) * 0.002
    speed = 1.0 + math.sin(phase * 1.7) * 0.006
    brightness = math.sin(phase * 2.3) * 0.004
    saturation = 1.0 + math.cos(phase * 1.1) * 0.008
    crf = 20 + (phase % 4)
    return zoom, speed, brightness, saturation, crf


def create_variants(
    source: Path,
    count: int,
    progress: Progress | None = None,
) -> list[Path]:
    source = source.expanduser().resolve()
    if not 1 <= count <= 100:
        raise VariantError("Varyasyon sayısı 1 ile 100 arasında olmalı")
    if not source.is_file() or source.stat().st_size <= 0:
        raise VariantError(f"Kaynak video bulunamadı veya boş: {source}")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise VariantError("FFmpeg ve FFprobe PATH üzerinde bulunmalı")

    output = source.parent / f"{source.stem}-web-varyasyonlar"
    output.mkdir(parents=True, exist_ok=True)
    has_audio = _probe_audio(ffprobe, source)
    results: list[Path] = []

    for index in range(1, count + 1):
        zoom, speed, brightness, saturation, crf = variant_parameters(index)
        target = output / f"{index}.mp4"
        if progress:
            progress(round((index - 1) * 100 / count), f"Varyasyon {index}/{count} hazırlanıyor")
        vf = (
            f"scale=ceil(iw*{zoom:.6f}/2)*2:ceil(ih*{zoom:.6f}/2)*2,"
            f"crop=trunc(iw/{zoom:.6f}/2)*2:trunc(ih/{zoom:.6f}/2)*2,"
            f"setpts=PTS/{speed:.6f},"
            f"eq=brightness={brightness:.6f}:saturation={saturation:.6f},"
            "fps=30,format=yuv420p,setsar=1"
        )
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-map", "0:v:0", "-vf", vf, "-c:v", "libx264", "-preset", "medium",
            "-crf", str(crf), "-profile:v", "high", "-level:v", "4.1",
            "-movflags", "+faststart", "-map_metadata", "-1",
        ]
        if has_audio:
            command += [
                "-map", "0:a:0", "-af", f"atempo={speed:.6f},aresample=48000",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            ]
        else:
            command += ["-an"]
        command += ["-shortest", str(target)]
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if result.returncode or not target.is_file() or target.stat().st_size <= 0:
            target.unlink(missing_ok=True)
            raise VariantError(result.stderr.strip() or f"{index}.mp4 oluşturulamadı")
        results.append(target)
        if progress:
            progress(round(index * 100 / count), f"Varyasyon {index}/{count} hazır: {target.name}")
    return results


def create_five_variants(source: Path, progress: Progress | None = None) -> list[Path]:
    """Backward-compatible wrapper."""
    return create_variants(source, 5, progress)
