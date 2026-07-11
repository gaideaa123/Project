from __future__ import annotations

"""Material editorial cut engine, not metadata or fingerprint manipulation."""

import json
import math
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import originality_qa

Progress = Callable[[int, str], None]
MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}

class VariantError(RuntimeError):
 pass

@dataclass(frozen=True)
class EditorialPlan:
 name: str
 scene_fractions: tuple[float, ...]
 coverage: float
 speed: float
 zoom: float
 saturation: float
 contrast: float
 brightness: float

BASE_PLANS = (
 EditorialPlan("payoff-context-proof", (.72, .08, .42), .74, 1.000, 1.020, 1.01, 1.02, 0.000),
 EditorialPlan("problem-proof-result", (.16, .48, .80), .70, 1.025, 1.035, .99, 1.03, -.004),
 EditorialPlan("rapid-three-act", (.36, .76, .10, .58), .68, 1.035, 1.050, 1.03, 1.04, .003),
 EditorialPlan("midstory-context-payoff", (.52, .05, .84), .76, .990, 1.025, .98, 1.01, -.003),
 EditorialPlan("result-detail-origin", (.82, .32, .04), .72, 1.015, 1.045, 1.02, 1.03, .002),
 EditorialPlan("context-reveal-detail", (.08, .66, .40, .88), .66, 1.005, 1.030, 1.00, 1.02, .001),
)

def video_info(ffprobe: str, path: Path) -> tuple[float, bool]:
 result = subprocess.run(
  [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)],
  capture_output=True, text=True, encoding="utf-8", errors="replace",
 )
 if result.returncode:
  raise VariantError(result.stderr.strip() or "FFprobe videoyu okuyamadı")
 try:
  data = json.loads(result.stdout)
  duration = float(data.get("format", {}).get("duration") or 0)
  has_audio = any(stream.get("codec_type") == "audio" for stream in data.get("streams", []))
 except Exception as exc:
  raise VariantError("Video bilgisi çözümlenemedi") from exc
 if duration <= 0:
  raise VariantError(f"Video süresi okunamadı: {path.name}")
 return duration, has_audio

def plan_for(index: int) -> EditorialPlan:
 if index < 1:
  raise VariantError("Varyasyon numarası 1 veya daha büyük olmalı")
 base = BASE_PLANS[(index - 1) % len(BASE_PLANS)]
 cycle = (index - 1) // len(BASE_PLANS)
 if cycle == 0:
  return base
 shift = ((cycle * 0.137) % .42) - .21
 fractions = tuple(min(.92, max(.04, value + shift)) for value in base.scene_fractions)
 rotate = cycle % len(fractions)
 fractions = fractions[rotate:] + fractions[:rotate]
 return EditorialPlan(
  f"{base.name}-{cycle + 1}", fractions,
  max(.60, base.coverage - (cycle % 3) * .025),
  min(1.04, max(.98, base.speed + math.sin(index * 1.21) * .008)),
  min(1.07, base.zoom + (cycle % 3) * .006),
  base.saturation, base.contrast, base.brightness,
 )

def _segment_start(duration: float, fraction: float, length: float) -> float:
 return min(max(.10, duration * fraction), max(.10, duration - length - .10))

def _visual_chain(label: int, plan: EditorialPlan) -> str:
 return (
  f"[{label}:v]setpts=(PTS-STARTPTS)/{plan.speed:.6f},"
  "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
  f"scale=iw*{plan.zoom:.6f}:ih*{plan.zoom:.6f}:flags=lanczos,"
  "crop=1080:1920,"
  f"eq=saturation={plan.saturation:.6f}:contrast={plan.contrast:.6f}:brightness={plan.brightness:.6f},"
  "unsharp=5:5:0.22:3:3:0.0,fps=30,settb=AVTB,setsar=1,format=yuv420p"
 )

def _build_command(ffmpeg: str, source: Path, target: Path, duration: float, has_audio: bool, plan: EditorialPlan) -> list[str]:
 command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
 count = len(plan.scene_fractions)
 segment_length = max(1.35, duration * plan.coverage / count)
 segment_length = min(segment_length, max(1.35, duration * .34))
 for fraction in plan.scene_fractions:
  start = _segment_start(duration, fraction, segment_length)
  command += ["-ss", f"{start:.3f}", "-t", f"{segment_length:.3f}", "-i", str(source)]
 filters: list[str] = []
 video_labels: list[str] = []
 audio_labels: list[str] = []
 for input_index in range(count):
  video_label = f"v{input_index}"
  filters.append(f"{_visual_chain(input_index, plan)}[{video_label}]")
  video_labels.append(f"[{video_label}]")
  if has_audio:
   audio_label = f"a{input_index}"
   filters.append(
    f"[{input_index}:a]asetpts=PTS-STARTPTS,atempo={plan.speed:.6f},"
    "aresample=48000:async=1:first_pts=0,"
    f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[{audio_label}]"
   )
   audio_labels.append(f"[{audio_label}]")
 filters.append("".join(video_labels) + f"concat=n={count}:v=1:a=0[out_v]")
 if has_audio:
  filters.append("".join(audio_labels) + f"concat=n={count}:v=0:a=1[out_a]")
 command += ["-filter_complex", ";".join(filters), "-map", "[out_v]"]
 if has_audio:
  command += ["-map", "[out_a]"]
 crf = 19 + (sum(ord(character) for character in plan.name) % 3)
 command += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-profile:v", "high", "-level:v", "4.1", "-pix_fmt", "yuv420p", "-r", "30", "-fps_mode", "cfr"]
 command += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"] if has_audio else ["-an"]
 command += ["-movflags", "+faststart", "-map_metadata", "-1", "-shortest", str(target)]
 return command

def create_variants(source: Path, count: int, progress: Progress | None = None, cold_open: bool = True, output_dir: Path | None = None) -> list[Path]:
 source = source.expanduser().resolve()
 if not 1 <= count <= 100:
  raise VariantError("Varyasyon sayısı 1 ile 100 arasında olmalı")
 if not source.is_file() or source.suffix.lower() not in MEDIA_EXTENSIONS:
  raise VariantError("Geçerli bir input video seçin")
 ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
 if not ffmpeg or not ffprobe:
  raise VariantError("FFmpeg ve FFprobe PATH üzerinde bulunamadı")
 try:
  originality_qa.assert_source_eligible(source)
 except originality_qa.OriginalityQAError as exc:
  raise VariantError(str(exc)) from exc
 output = (output_dir or source.parent / f"{source.stem}-editorial-varyasyonlar").expanduser().resolve()
 output.mkdir(parents=True, exist_ok=True)
 duration, has_audio = video_info(ffprobe, source)
 results: list[Path] = []
 reports: list[originality_qa.OriginalityReport] = []
 for index in range(1, count + 1):
  plan = plan_for(index)
  target = output / f"{index}.mp4"; temporary = output / f".{index}.rendering.mp4"
  temporary.unlink(missing_ok=True)
  if progress:
   progress(round((index - 1) * 100 / count), f"{index}/{count}: {plan.name} sahne kurgusu hazırlanıyor")
  done = subprocess.run(_build_command(ffmpeg, source, temporary, duration, has_audio, plan), capture_output=True, text=True, encoding="utf-8", errors="replace")
  if done.returncode or not temporary.exists() or temporary.stat().st_size == 0:
   temporary.unlink(missing_ok=True)
   raise VariantError(done.stderr.strip() or f"{index}.mp4 editoryal üretimi başarısız")
  try:
   report = originality_qa.assert_output_eligible(temporary, reports)
  except originality_qa.OriginalityQAError as exc:
   temporary.unlink(missing_ok=True)
   raise VariantError(str(exc)) from exc
  temporary.replace(target); reports.append(report); results.append(target.resolve())
  if progress:
   progress(round(index * 100 / count), f"{index}/{count}: {plan.name} kalite ve farklılık kontrolünü geçti")
 return results

def create_five_variants(source: Path, progress: Progress | None = None) -> list[Path]:
 return create_variants(source, 5, progress, True)
