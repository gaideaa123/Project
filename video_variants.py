from __future__ import annotations

"""Editorial cold-open variant engine restored from the original implementation."""

import json
import random
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

Progress = Callable[[int, str], None]
MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


class VariantError(RuntimeError):
    pass


def video_info(ffprobe: str, path: Path) -> tuple[float, bool]:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode:
        raise VariantError(result.stderr.strip() or "FFprobe videoyu okuyamadı")
    try:
        data = json.loads(result.stdout)
        duration = float(data.get("format", {}).get("duration") or 0)
        has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise VariantError("Video bilgisi çözümlenemedi") from exc
    if duration <= 0:
        raise VariantError(f"Video süresi okunamadı: {path.name}")
    return duration, has_audio


def visual_chain(
    label: str,
    speed: float,
    zoom: float,
    saturation: float,
    contrast: float,
    brightness: float,
    teaser: bool = False,
) -> str:
    timing = "setpts=PTS-STARTPTS" if teaser else f"setpts=(PTS-STARTPTS)/{speed:.6f}"
    return (
        f"[{label}:v]{timing},"
        "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
        f"scale=iw*{zoom:.6f}:ih*{zoom:.6f}:flags=lanczos,"
        "crop=1080:1920,"
        f"eq=saturation={saturation:.6f}:contrast={contrast:.6f}:brightness={brightness:.6f},"
        "unsharp=5:5:0.20:3:3:0.0,"
        "fps=30,settb=AVTB,setsar=1,format=yuv420p"
    )


def create_variants(
    source: Path,
    count: int,
    progress: Progress | None = None,
    cold_open: bool = True,
) -> list[Path]:
    source = source.expanduser().resolve()
    if not 1 <= count <= 100:
        raise VariantError("Varyasyon sayısı 1 ile 100 arasında olmalı")
    if not source.is_file() or source.suffix.lower() not in MEDIA_EXTENSIONS:
        raise VariantError("Geçerli bir input video seçin")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise VariantError("FFmpeg ve FFprobe PATH üzerinde bulunamadı")

    output = source.parent / f"{source.stem}-cold-open-varyasyonlar"
    output.mkdir(parents=True, exist_ok=True)
    duration, has_audio = video_info(ffprobe, source)
    rng = random.SystemRandom()
    results: list[Path] = []

    for index in range(1, count + 1):
        speed = rng.uniform(0.992, 1.012)
        zoom = rng.uniform(1.006, 1.025)
        saturation = rng.uniform(0.98, 1.04)
        contrast = rng.uniform(0.99, 1.03)
        brightness = rng.uniform(-0.008, 0.008)
        trim = min(rng.uniform(0.0, 0.10), max(0.0, duration - 1.0))
        teaser_duration = min(rng.uniform(0.75, 1.20), max(0.35, duration * 0.15))
        safe_latest = max(0.0, duration - teaser_duration - 0.2)
        teaser_start = min(
            duration * rng.choice((0.28, 0.42, 0.58, 0.70)), safe_latest
        )
        target = output / f"{index}.mp4"

        if cold_open:
            teaser_chain = visual_chain(
                "0", 1.0, zoom + 0.012, saturation, contrast, brightness, True
            )
            main_chain = visual_chain(
                "1", speed, zoom, saturation, contrast, brightness, False
            )
            filters = [
                f"{teaser_chain}[teaser_v]",
                f"{main_chain}[main_v]",
                "[teaser_v][main_v]concat=n=2:v=1:a=0[out_v]",
            ]
            if has_audio:
                filters += [
                    "[0:a]asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,"
                    "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[teaser_a]",
                    f"[1:a]asetpts=PTS-STARTPTS,atempo={speed:.6f},"
                    "aresample=48000:async=1:first_pts=0,"
                    "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                    "loudnorm=I=-14:TP=-1.5:LRA=11[main_a]",
                    "[teaser_a][main_a]concat=n=2:v=0:a=1[out_a]",
                ]
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{teaser_start:.3f}", "-t", f"{teaser_duration:.3f}",
                "-i", str(source), "-ss", f"{trim:.3f}", "-i", str(source),
                "-filter_complex", ";".join(filters), "-map", "[out_v]",
            ]
            if has_audio:
                command += ["-map", "[out_a]"]
        else:
            chain = visual_chain("0", speed, zoom, saturation, contrast, brightness, False)
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{trim:.3f}", "-i", str(source),
                "-filter_complex", f"{chain}[out_v]", "-map", "[out_v]",
            ]
            if has_audio:
                command += [
                    "-map", "0:a:0", "-af", f"atempo={speed:.6f},"
                    "aresample=48000:async=1:first_pts=0,loudnorm=I=-14:TP=-1.5:LRA=11",
                ]

        command += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-profile:v", "high", "-level:v", "4.1", "-pix_fmt", "yuv420p",
            "-r", "30", "-fps_mode", "cfr",
        ]
        if has_audio:
            command += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
        else:
            command += ["-an"]
        command += ["-movflags", "+faststart", "-map_metadata", "-1", "-shortest", str(target)]

        if progress:
            mode = "cold-open + ana kurgu" if cold_open else "ana kurgu"
            progress(round((index - 1) * 100 / count), f"{index}/{count}: {mode}")
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if completed.returncode:
            target.unlink(missing_ok=True)
            raise VariantError(completed.stderr.strip() or "FFmpeg üretimi başarısız")
        if not target.exists() or target.stat().st_size == 0:
            target.unlink(missing_ok=True)
            raise VariantError("FFmpeg boş çıktı üretti")
        results.append(target.resolve())
        if progress:
            progress(round(index * 100 / count), f"{index}/{count}: {target.name} hazır")
    return results


def create_five_variants(source: Path, progress: Progress | None = None) -> list[Path]:
    return create_variants(source, 5, progress, cold_open=True)
