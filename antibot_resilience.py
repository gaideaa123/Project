from __future__ import annotations

"""Defensive anti-bot resilience fixtures and scoring.

No live TLS impersonation, CDP concealment, or browser fingerprint spoofing is
performed. The module generates labelled observations for owned WAF test suites
and collects browser-side evidence without changing the observed environment.
"""

import hashlib
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


class ResilienceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClientObservation:
    run_id: str
    tls_family: str
    ja4_label: str
    webdriver: bool
    chrome_runtime: bool
    notification_permission: str
    webgl_vendor: str
    webgl_renderer: str
    canvas_digest: str
    audio_digest: str
    font_count: int
    user_agent: str

    def validate(self) -> None:
        if not self.run_id.strip():
            raise ResilienceError("run_id boş")
        if self.notification_permission not in {"default", "granted", "denied"}:
            raise ResilienceError("geçersiz notification permission")
        for digest in (self.canvas_digest, self.audio_digest):
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ResilienceError("fingerprint digest SHA-256 olmalı")
        if self.font_count < 0:
            raise ResilienceError("font_count negatif olamaz")


@dataclass(frozen=True)
class DetectionResult:
    score: int
    labels: tuple[str, ...]

    @property
    def suspicious(self) -> bool:
        return self.score >= 50


class DefensiveDetector:
    """Explainable baseline used to compare WAF decisions in a test cohort."""

    def score(self, item: ClientObservation) -> DetectionResult:
        item.validate()
        score = 0
        labels: list[str] = []
        if item.webdriver:
            score += 45
            labels.append("webdriver-exposed")
        if not item.chrome_runtime and "Chrome" in item.user_agent:
            score += 20
            labels.append("chrome-runtime-mismatch")
        if not item.webgl_vendor or not item.webgl_renderer:
            score += 20
            labels.append("webgl-missing")
        if item.font_count < 3:
            score += 10
            labels.append("font-surface-small")
        if item.tls_family == "datacenter-default":
            score += 20
            labels.append("tls-datacenter-baseline")
        if not item.ja4_label:
            score += 10
            labels.append("ja4-unclassified")
        return DetectionResult(min(score, 100), tuple(labels))


class LabelledFixtureFactory:
    """Produces deterministic records, not network or browser impersonation."""

    def __init__(self, seed: str):
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        self.random = random.Random(int.from_bytes(digest[:8], "big"))

    def build(self, run_id: str, cohort: str) -> ClientObservation:
        if cohort not in {"known-automation", "desktop-control", "inconsistent-client"}:
            raise ResilienceError(f"bilinmeyen cohort: {cohort}")
        token = lambda name: hashlib.sha256(f"{run_id}:{cohort}:{name}".encode()).hexdigest()
        if cohort == "known-automation":
            return ClientObservation(
                run_id, "datacenter-default", "automation-baseline", True,
                False, "default", "Google Inc.", "ANGLE (Software Renderer)",
                token("canvas"), token("audio"), 2, "Chrome Test Automation",
            )
        if cohort == "inconsistent-client":
            return ClientObservation(
                run_id, "browser-default", "inconsistent-lab-record", False,
                False, "default", "", "", token("canvas"), token("audio"),
                1, "Mozilla/5.0 Chrome/126.0",
            )
        return ClientObservation(
            run_id, "browser-default", "desktop-control", False, True,
            "default", "Google Inc.", "ANGLE (Hardware Renderer)",
            token("canvas"), token("audio"), 24, "Mozilla/5.0 Chrome/126.0",
        )


class ResilienceReport:
    def __init__(self, detector: DefensiveDetector | None = None):
        self.detector = detector or DefensiveDetector()

    def evaluate(self, observations: Iterable[ClientObservation]) -> dict[str, Any]:
        rows = []
        suspicious = 0
        for observation in observations:
            result = self.detector.score(observation)
            suspicious += int(result.suspicious)
            rows.append({
                "observation": asdict(observation),
                "detection": {"score": result.score, "labels": list(result.labels),
                              "suspicious": result.suspicious},
            })
        total = len(rows)
        return {
            "total": total,
            "suspicious": suspicious,
            "detection_rate": suspicious / total if total else 0.0,
            "rows": rows,
        }

    def write(self, path: Path, observations: Iterable[ClientObservation]) -> None:
        payload = self.evaluate(observations)
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


BROWSER_EVIDENCE_SCRIPT = r"""
async () => {
  const sha256 = async value => {
    const bytes = new TextEncoder().encode(value);
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    return [...new Uint8Array(hash)].map(v => v.toString(16).padStart(2, '0')).join('');
  };
  const canvas = document.createElement('canvas');
  canvas.width = 240; canvas.height = 80;
  const ctx = canvas.getContext('2d');
  ctx.font = '16px sans-serif';
  ctx.fillText('authorized resilience measurement', 4, 28);
  const gl = document.createElement('canvas').getContext('webgl');
  const debug = gl?.getExtension('WEBGL_debug_renderer_info');
  const vendor = debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : '';
  const renderer = debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : '';
  const fonts = ['Arial', 'Times New Roman', 'Courier New', 'Segoe UI', 'Roboto'];
  const fontCount = document.fonts?.check ? fonts.filter(f => document.fonts.check(`12px "${f}"`)).length : 0;
  return {
    webdriver: navigator.webdriver === true,
    chrome_runtime: Boolean(window.chrome && (window.chrome.runtime || window.chrome.app)),
    notification_permission: window.Notification?.permission || 'default',
    webgl_vendor: String(vendor || ''),
    webgl_renderer: String(renderer || ''),
    canvas_digest: await sha256(canvas.toDataURL()),
    audio_digest: await sha256(String(new (window.AudioContext || window.webkitAudioContext)().sampleRate)),
    font_count: fontCount,
    user_agent: navigator.userAgent
  };
}
"""
