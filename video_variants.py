from __future__ import annotations

"""Create five standards-compliant delivery variants for profile distribution."""

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

Progress = Callable[[int, str], None]


class VariantError(RuntimeError):
    pass


# Small delivery-grade changes keep the picture natural while producing five
# independently encoded files. This is transcoding, not platform fingerprint evasion.
PRESETS = (
    (1.000, 1.000, 0.000, 1.000),
    (1.006, 0.998, 0.006, 1.008),
    (1.012, 1.003, -0.004, 0.996),
    (1.018, 0.996, 0.004, 1.012),
    (1.024, 1.002, -0.006, 0.992),
)


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


def create_five_variants(source: Path, progress: Progress | None = None) -> list[Path]:
    source = source.expanduser().resolve()
    if not source.is_file() or source.stat().st_size <= 0:
        raise VariantError(f"Kaynak video bulunamadı veya boş: {source}")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise VariantError("FFmpeg ve FFprobe PATH üzerinde bulunmalı")

    output = source.parent / f"{source.stem}-web-varyasyonlar"
    output.mkdir(parents=True, exist_ok=True)
    has_audio = _probe_audio(ffprobe, source)
    results: list[Path] = []

    for index, (zoom, speed, brightness, saturation) in enumerate(PRESETS, 1):
        target = output / f"{index}.mp4"
        if progress:
            progress((index - 1) * 20, f"Varyasyon {index}/5 hazırlanıyor")
        vf = (
            f"scale=ceil(iw*{zoom}/2)*2:ceil(ih*{zoom}/2)*2,"
            f"crop=trunc(iw/{zoom}/2)*2:trunc(ih/{zoom}/2)*2,"
            f"setpts=PTS/{speed},eq=brightness={brightness}:saturation={saturation},"
            "fps=30,format=yuv420p,setsar=1"
        )
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-map", "0:v:0", "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", str(20 + (index % 3)),
            "-profile:v", "high", "-level:v", "4.1", "-movflags", "+faststart",
            "-map_metadata", "-1",
        ]
        if has_audio:
            # atempo is inverse of video setpts speed to keep A/V duration aligned.
            command += [
                "-map", "0:a:0", "-af", f"atempo={speed},aresample=48000",
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
            progress(index * 20, f"Varyasyon {index}/5 hazır: {target.name}")
    return results
