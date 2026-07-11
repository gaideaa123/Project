from __future__ import annotations

"""One-click editorial variant engine.

Each output gets a materially different cold open, pacing, framing and visual
structure. The goal is useful account-specific editing, not metadata tricks or
fingerprint spoofing. Outputs remain numbered for app_tr's existing assignment:
1.mp4 -> first profile, 2.mp4 -> second profile, and so on.
"""

import json
import math
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Progress = Callable[[int, str], None]
MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


class VariantError(RuntimeError):
    pass


@dataclass(frozen=True)
class EditorialPlan:
    name: str
    hook_fractions: tuple[float, ...]
    hook_lengths: tuple[float, ...]
    main_start: float
    main_end_trim: float
    speed: float
    zoom: float
    saturation: float
    contrast: float
    brightness: float
    hook_zoom: float


BASE_PLANS = (
    EditorialPlan("payoff-first", (.72,), (1.15,), .02, .00, 1.000, 1.010, 1.01, 1.01, 0.000, 1.070),
    EditorialPlan("problem-first", (.18,), (1.35,), .08, .20, 1.025, 1.025, .98, 1.03, -.006, 1.085),
    EditorialPlan("double-reveal", (.38, .78), (.62, .68), .03, .35, 1.012, 1.040, 1.04, 1.02, .004, 1.110),
    EditorialPlan("mid-story-open", (.52,), (1.55,), .12, .10, .985, 1.018, .97, 1.00, -.004, 1.060),
    EditorialPlan("rapid-montage", (.24, .55, .84), (.42, .46, .48), .06, .45, 1.035, 1.050, 1.03, 1.04, .003, 1.125),
    EditorialPlan("context-then-payoff", (.10, .68), (.78, .82), .15, .15, .995, 1.030, 1.00, 1.02, .002, 1.095),
)


def video_info(ffprobe: str, path: Path) -> tuple[float, bool]:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
         "-of", "json", str(path)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode:
        raise VariantError(result.stderr.strip() or "FFprobe videoyu okuyamadı")
    try:
        data = json.loads(result.stdout)
        duration = float(data.get("format", {}).get("duration") or 0)
        has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    except Exception as exc:
        raise VariantError("Video bilgisi çözümlenemedi") from exc
    if duration <= 0:
        raise VariantError(f"Video süresi okunamadı: {path.name}")
    return duration, has_audio


def plan_for(index: int) -> EditorialPlan:
    """Return a bounded deterministic plan for any 1-based account index."""
    if index < 1:
        raise VariantError("Varyasyon numarası 1 veya daha büyük olmalı")
    base = BASE_PLANS[(index - 1) % len(BASE_PLANS)]
    cycle = (index - 1) // len(BASE_PLANS)
    if cycle == 0:
        return base
    # Further accounts keep the same editorial grammar but use different scene
    # positions and pacing. Values stay conservative enough for clean playback.
    shift = ((cycle * 0.113) % .34) - .17
    fractions = tuple(min(.90, max(.08, value + shift)) for value in base.hook_fractions)
    speed = min(1.045, max(.975, base.speed + math.sin(index * 1.37) * .008))
    zoom = min(1.065, base.zoom + (cycle % 3) * .006)
    return EditorialPlan(
        f"{base.name}-{cycle + 1}", fractions, base.hook_lengths,
        min(.22, base.main_start + (cycle % 4) * .015),
        min(.60, base.main_end_trim + (cycle % 3) * .08),
        speed, zoom, base.saturation, base.contrast, base.brightness,
        min(1.14, base.hook_zoom + (cycle % 2) * .012),
    )


def _safe_segment_start(duration: float, fraction: float, length: float) -> float:
    margin = min(.25, duration * .02)
    return min(max(margin, duration * fraction), max(margin, duration - length - margin))


def _visual_chain(label: int, speed: float, zoom: float, saturation: float,
                  contrast: float, brightness: float, hook: bool) -> str:
    timing = "setpts=PTS-STARTPTS" if hook else f"setpts=(PTS-STARTPTS)/{speed:.6f}"
    # Portrait editorial crop with deliberate account-specific punch-in.
    return (
        f"[{label}:v]{timing},"
        "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
        f"scale=iw*{zoom:.6f}:ih*{zoom:.6f}:flags=lanczos,"
        "crop=1080:1920,"
        f"eq=saturation={saturation:.6f}:contrast={contrast:.6f}:brightness={brightness:.6f},"
        "unsharp=5:5:0.22:3:3:0.0,fps=30,settb=AVTB,setsar=1,format=yuv420p"
    )


def _build_command(ffmpeg: str, source: Path, target: Path, duration: float,
                   has_audio: bool, plan: EditorialPlan) -> list[str]:
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    hook_count = len(plan.hook_fractions)
    for fraction, requested in zip(plan.hook_fractions, plan.hook_lengths):
        length = min(requested, max(.35, duration * .12))
        start = _safe_segment_start(duration, fraction, length)
        command += ["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(source)]

    main_start = min(plan.main_start, max(0.0, duration - 1.0))
    main_length = max(.75, duration - main_start - plan.main_end_trim)
    command += ["-ss", f"{main_start:.3f}", "-t", f"{main_length:.3f}", "-i", str(source)]

    filters: list[str] = []
    video_labels: list[str] = []
    audio_labels: list[str] = []
    for input_index in range(hook_count):
        label = f"hook_v{input_index}"
        filters.append(
            f"{_visual_chain(input_index, 1.0, plan.hook_zoom, plan.saturation, plan.contrast, plan.brightness, True)}[{label}]"
        )
        video_labels.append(f"[{label}]")
        if has_audio:
            audio = f"hook_a{input_index}"
            filters.append(
                f"[{input_index}:a]asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,"
                f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[{audio}]"
            )
            audio_labels.append(f"[{audio}]")

    main_index = hook_count
    filters.append(
        f"{_visual_chain(main_index, plan.speed, plan.zoom, plan.saturation, plan.contrast, plan.brightness, False)}[main_v]"
    )
    video_labels.append("[main_v]")
    filters.append("".join(video_labels) + f"concat=n={len(video_labels)}:v=1:a=0[out_v]")

    if has_audio:
        filters.append(
            f"[{main_index}:a]asetpts=PTS-STARTPTS,atempo={plan.speed:.6f},"
            "aresample=48000:async=1:first_pts=0,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            "loudnorm=I=-14:TP=-1.5:LRA=11[main_a]"
        )
        audio_labels.append("[main_a]")
        filters.append("".join(audio_labels) + f"concat=n={len(audio_labels)}:v=0:a=1[out_a]")

    command += ["-filter_complex", ";".join(filters), "-map", "[out_v]"]
    if has_audio:
        command += ["-map", "[out_a]"]
    crf = 20 + (sum(ord(char) for char in plan.name) % 3)
    command += [
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-profile:v", "high", "-level:v", "4.1", "-pix_fmt", "yuv420p",
        "-r", "30", "-fps_mode", "cfr",
    ]
    command += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"] if has_audio else ["-an"]
    command += ["-movflags", "+faststart", "-map_metadata", "-1", "-shortest", str(target)]
    return command


def create_variants(source: Path, count: int, progress: Progress | None = None,
                    cold_open: bool = True, output_dir: Path | None = None) -> list[Path]:
    """Create numbered account variants in one click, preserving app_tr's API."""
    source = source.expanduser().resolve()
    if not 1 <= count <= 100:
        raise VariantError("Varyasyon sayısı 1 ile 100 arasında olmalı")
    if not source.is_file() or source.suffix.lower() not in MEDIA_EXTENSIONS:
        raise VariantError("Geçerli bir input video seçin")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise VariantError("FFmpeg ve FFprobe PATH üzerinde bulunamadı")
    output = (output_dir or source.parent / f"{source.stem}-editorial-varyasyonlar").expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    duration, has_audio = video_info(ffprobe, source)
    if duration < 3.0:
        raise VariantError("Ciddi editoryal varyasyon için video en az 3 saniye olmalı")

    results: list[Path] = []
    for index in range(1, count + 1):
        plan = plan_for(index)
        target = output / f"{index}.mp4"
        temporary = output / f".{index}.rendering.mp4"
        temporary.unlink(missing_ok=True)
        if progress:
            progress(round((index - 1) * 100 / count), f"{index}/{count}: {plan.name} kurgusu hazırlanıyor")
        command = _build_command(ffmpeg, source, temporary, duration, has_audio, plan)
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if done.returncode or not temporary.exists() or temporary.stat().st_size == 0:
            temporary.unlink(missing_ok=True)
            raise VariantError(done.stderr.strip() or f"{index}.mp4 editoryal üretimi başarısız")
        temporary.replace(target)
        results.append(target.resolve())
        if progress:
            progress(round(index * 100 / count), f"{index}/{count}: {plan.name} hazır -> {target.name}")
    return results


def create_five_variants(source: Path, progress: Progress | None = None) -> list[Path]:
    return create_variants(source, 5, progress, True)
