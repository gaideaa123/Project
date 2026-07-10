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

class VariantError(RuntimeError): pass

def video_info(ffprobe: str, path: Path) -> tuple[float, bool]:
    result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode: raise VariantError(result.stderr.strip() or "FFprobe videoyu okuyamadı")
    try:
        data = json.loads(result.stdout); duration = float(data.get("format", {}).get("duration") or 0)
        has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    except Exception as exc: raise VariantError("Video bilgisi çözümlenemedi") from exc
    if duration <= 0: raise VariantError(f"Video süresi okunamadı: {path.name}")
    return duration, has_audio

def visual_chain(label, speed, zoom, saturation, contrast, brightness, teaser=False):
    timing = "setpts=PTS-STARTPTS" if teaser else f"setpts=(PTS-STARTPTS)/{speed:.6f}"
    return (f"[{label}:v]{timing},scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
            f"scale=iw*{zoom:.6f}:ih*{zoom:.6f}:flags=lanczos,crop=1080:1920,"
            f"eq=saturation={saturation:.6f}:contrast={contrast:.6f}:brightness={brightness:.6f},"
            "unsharp=5:5:0.20:3:3:0.0,fps=30,settb=AVTB,setsar=1,format=yuv420p")

def create_variants(source: Path, count: int, progress: Progress | None = None, cold_open: bool = True, output_dir: Path | None = None) -> list[Path]:
    source = source.expanduser().resolve()
    if not 1 <= count <= 100: raise VariantError("Varyasyon sayısı 1 ile 100 arasında olmalı")
    if not source.is_file() or source.suffix.lower() not in MEDIA_EXTENSIONS: raise VariantError("Geçerli bir input video seçin")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe: raise VariantError("FFmpeg ve FFprobe PATH üzerinde bulunamadı")
    output = (output_dir or source.parent / f"{source.stem}-cold-open-varyasyonlar").expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    duration, has_audio = video_info(ffprobe, source); rng = random.SystemRandom(); results = []
    for index in range(1, count + 1):
        speed = rng.uniform(.992, 1.012); zoom = rng.uniform(1.006, 1.025)
        saturation = rng.uniform(.98, 1.04); contrast = rng.uniform(.99, 1.03); brightness = rng.uniform(-.008, .008)
        trim = min(rng.uniform(0, .10), max(0, duration - 1)); teaser_duration = min(rng.uniform(.75, 1.20), max(.35, duration * .15))
        teaser_start = min(duration * rng.choice((.28, .42, .58, .70)), max(0, duration - teaser_duration - .2)); target = output / f"{index}.mp4"
        teaser = visual_chain("0", 1, zoom + .012, saturation, contrast, brightness, True)
        main = visual_chain("1", speed, zoom, saturation, contrast, brightness)
        filters = [f"{teaser}[teaser_v]", f"{main}[main_v]", "[teaser_v][main_v]concat=n=2:v=1:a=0[out_v]"]
        if has_audio:
            filters += ["[0:a]asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[teaser_a]", f"[1:a]asetpts=PTS-STARTPTS,atempo={speed:.6f},aresample=48000:async=1:first_pts=0,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,loudnorm=I=-14:TP=-1.5:LRA=11[main_a]", "[teaser_a][main_a]concat=n=2:v=0:a=1[out_a]"]
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{teaser_start:.3f}", "-t", f"{teaser_duration:.3f}", "-i", str(source), "-ss", f"{trim:.3f}", "-i", str(source), "-filter_complex", ";".join(filters), "-map", "[out_v]"]
        if has_audio: command += ["-map", "[out_a]"]
        command += ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-profile:v", "high", "-level:v", "4.1", "-pix_fmt", "yuv420p", "-r", "30", "-fps_mode", "cfr"]
        command += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"] if has_audio else ["-an"]
        command += ["-movflags", "+faststart", "-map_metadata", "-1", "-shortest", str(target)]
        if progress: progress(round((index - 1) * 100 / count), f"{index}/{count}: cold-open + ana kurgu")
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if done.returncode or not target.exists() or target.stat().st_size == 0:
            target.unlink(missing_ok=True); raise VariantError(done.stderr.strip() or "FFmpeg üretimi başarısız")
        results.append(target.resolve())
        if progress: progress(round(index * 100 / count), f"{index}/{count}: {target.name} hazır")
    return results

def create_five_variants(source: Path, progress: Progress | None = None) -> list[Path]:
    return create_variants(source, 5, progress, True)
