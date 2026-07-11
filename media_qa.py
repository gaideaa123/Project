from __future__ import annotations

"""Reproducible browser and media QA harness.

This module intentionally does not hide automation, spoof fingerprints, alter TLS,
or synthesize platform analytics. It validates real browser playback in authorized
test environments and keeps every test session isolated.
"""

import asyncio
import hashlib
import json
import math
import os
import random
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, Playwright


class MediaQAError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrowserProfile:
    browser: str = "chromium"
    locale: str = "tr-TR"
    timezone_id: str = "Europe/Istanbul"
    width: int = 1366
    height: int = 768
    color_scheme: str = "light"
    device_scale_factor: float = 1.0

    def validate(self) -> None:
        if self.browser not in {"chromium", "firefox", "webkit"}:
            raise MediaQAError(f"Desteklenmeyen tarayıcı: {self.browser}")
        if self.width < 800 or self.height < 600:
            raise MediaQAError("Viewport masaüstü testi için çok küçük")
        if self.color_scheme not in {"light", "dark", "no-preference"}:
            raise MediaQAError("Geçersiz renk şeması")
        if not 0.5 <= self.device_scale_factor <= 4.0:
            raise MediaQAError("Geçersiz device scale factor")


@dataclass(frozen=True)
class PlaybackReport:
    visible: bool
    intersection_ratio: float
    ready_state: int
    network_state: int
    start_time: float
    current_time: float
    advanced_by: float
    presented_frames: int
    dropped_frames: int
    decoded_width: int
    decoded_height: int
    buffered_seconds: float
    paused: bool
    ended: bool

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "PlaybackReport":
        return cls(**{field: value[field] for field in cls.__dataclass_fields__})

    def assert_healthy(self, minimum_advance: float = 1.0) -> None:
        failures: list[str] = []
        if not self.visible or self.intersection_ratio < 0.5:
            failures.append("video viewport içinde yeterince görünür değil")
        if self.ready_state < 3:
            failures.append(f"readyState yetersiz: {self.ready_state}")
        if self.advanced_by < minimum_advance:
            failures.append(f"playback yalnız {self.advanced_by:.2f}s ilerledi")
        if self.decoded_width <= 0 or self.decoded_height <= 0:
            failures.append("decode edilmiş görüntü boyutu yok")
        if self.buffered_seconds <= 0:
            failures.append("media buffer ilerlemedi")
        if failures:
            raise MediaQAError("; ".join(failures))


PLAYBACK_PROBE = r"""
async ({selector, sampleMs}) => {
  const video = document.querySelector(selector);
  if (!(video instanceof HTMLVideoElement)) {
    throw new Error(`Video bulunamadı: ${selector}`);
  }
  video.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
  const ratio = await new Promise(resolve => {
    const observer = new IntersectionObserver(entries => {
      resolve(entries[0]?.intersectionRatio || 0);
      observer.disconnect();
    }, {threshold: [0, .25, .5, .75, 1]});
    observer.observe(video);
  });
  const rect = video.getBoundingClientRect();
  const visible = ratio >= .5 && rect.width > 0 && rect.height > 0;
  const startTime = video.currentTime;
  const qualityBefore = video.getVideoPlaybackQuality?.();
  await video.play();
  let presentedFrames = 0;
  if ('requestVideoFrameCallback' in video) {
    await new Promise((resolve, reject) => {
      const deadline = performance.now() + sampleMs;
      const timer = setTimeout(() => {
        if (presentedFrames === 0) reject(new Error('Decode edilmiş frame alınamadı'));
        else resolve();
      }, sampleMs + 1500);
      const sample = () => {
        presentedFrames += 1;
        if (performance.now() >= deadline) {
          clearTimeout(timer);
          resolve();
        } else {
          video.requestVideoFrameCallback(sample);
        }
      };
      video.requestVideoFrameCallback(sample);
    });
  } else {
    await new Promise(resolve => setTimeout(resolve, sampleMs));
  }
  let bufferedSeconds = 0;
  for (let i = 0; i < video.buffered.length; i++) {
    bufferedSeconds += Math.max(0, video.buffered.end(i) - video.buffered.start(i));
  }
  const qualityAfter = video.getVideoPlaybackQuality?.();
  return {
    visible,
    intersection_ratio: ratio,
    ready_state: video.readyState,
    network_state: video.networkState,
    start_time: startTime,
    current_time: video.currentTime,
    advanced_by: video.currentTime - startTime,
    presented_frames: presentedFrames || Math.max(0,
      (qualityAfter?.totalVideoFrames || 0) - (qualityBefore?.totalVideoFrames || 0)),
    dropped_frames: Math.max(0,
      (qualityAfter?.droppedVideoFrames || 0) - (qualityBefore?.droppedVideoFrames || 0)),
    decoded_width: video.videoWidth,
    decoded_height: video.videoHeight,
    buffered_seconds: bufferedSeconds,
    paused: video.paused,
    ended: video.ended
  };
}
"""


class DeterministicInput:
    """Seeded input variation for repeatable QA, not bot-detection evasion."""

    def __init__(self, seed: str):
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        self.random = random.Random(int.from_bytes(digest[:8], "big"))

    def bezier_points(
        self, start: tuple[float, float], end: tuple[float, float], steps: int = 24
    ) -> list[tuple[float, float]]:
        if steps < 2:
            raise MediaQAError("Bezier en az iki adım gerektirir")
        sx, sy = start
        ex, ey = end
        dx, dy = ex - sx, ey - sy
        bend = max(20.0, math.hypot(dx, dy) * 0.18)
        c1 = (sx + dx * 0.33 + self.random.uniform(-bend, bend), sy + dy * 0.33)
        c2 = (sx + dx * 0.66, sy + dy * 0.66 + self.random.uniform(-bend, bend))
        points = []
        for index in range(1, steps + 1):
            t = index / steps
            u = 1 - t
            x = u**3 * sx + 3 * u**2 * t * c1[0] + 3 * u * t**2 * c2[0] + t**3 * ex
            y = u**3 * sy + 3 * u**2 * t * c1[1] + 3 * u * t**2 * c2[1] + t**3 * ey
            points.append((x, y))
        return points

    async def move(self, page: Page, start: tuple[float, float], end: tuple[float, float]) -> None:
        await page.mouse.move(*start)
        for x, y in self.bezier_points(start, end):
            await page.mouse.move(x, y)
            await asyncio.sleep(self.random.uniform(0.004, 0.014))

    async def type(self, page: Page, selector: str, text: str) -> None:
        field = page.locator(selector)
        await field.click()
        for character in text:
            await field.press_sequentially(character, delay=self.random.randint(25, 85))

    async def scroll(self, page: Page, distance: int, steps: int = 18) -> None:
        remaining = float(distance)
        for index in range(steps):
            fraction = math.exp(-index / max(1, steps / 4))
            delta = remaining * fraction / max(1.0, sum(math.exp(-i / max(1, steps / 4)) for i in range(steps)))
            await page.mouse.wheel(0, delta)
            await asyncio.sleep(self.random.uniform(0.01, 0.035))


class SessionArtifacts:
    def __init__(self, root: Path, run_id: str):
        self.root = root.resolve() / run_id
        self.root.mkdir(parents=True, exist_ok=False)
        self.trace = self.root / "trace.zip"
        self.result = self.root / "playback.json"
        self.screenshot = self.root / "page.png"

    def write_report(self, report: PlaybackReport, metadata: dict[str, Any]) -> None:
        payload = {"playback": asdict(report), "metadata": metadata}
        temporary = self.result.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.result)


class BrowserSession:
    def __init__(
        self,
        browser: Browser,
        profile: BrowserProfile,
        artifact_root: Path,
        allowed_hosts: Iterable[str],
        storage_state: Path | None = None,
    ):
        profile.validate()
        self.browser = browser
        self.profile = profile
        self.run_id = uuid.uuid4().hex
        self.artifacts = SessionArtifacts(artifact_root, self.run_id)
        self.allowed_hosts = {host.casefold() for host in allowed_hosts}
        self.storage_state = storage_state.resolve() if storage_state else None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.observed_requests: list[str] = []

    async def __aenter__(self) -> "BrowserSession":
        options: dict[str, Any] = {
            "locale": self.profile.locale,
            "timezone_id": self.profile.timezone_id,
            "viewport": {"width": self.profile.width, "height": self.profile.height},
            "screen": {"width": self.profile.width, "height": self.profile.height},
            "color_scheme": self.profile.color_scheme,
            "device_scale_factor": self.profile.device_scale_factor,
            "service_workers": "block",
        }
        if self.storage_state and self.storage_state.is_file():
            options["storage_state"] = str(self.storage_state)
        self.context = await self.browser.new_context(**options)
        await self.context.tracing.start(screenshots=True, snapshots=True, sources=True)
        self.context.on("request", lambda request: self.observed_requests.append(request.url))
        self.page = await self.context.new_page()
        return self

    async def goto(self, url: str) -> None:
        if not self.page or not self.context:
            raise MediaQAError("Session başlatılmadı")
        host = (urlparse(url).hostname or "").casefold()
        if host not in self.allowed_hosts:
            raise MediaQAError(f"Hedef host izinli test ortamı değil: {host}")
        await self.context.set_extra_http_headers({
            "X-Test-Run-ID": self.run_id,
            "X-Automation-Purpose": "media-qa",
        })
        await self.page.goto(url, wait_until="domcontentloaded")

    async def probe_playback(self, selector: str = "video", sample_ms: int = 3500) -> PlaybackReport:
        if not self.page:
            raise MediaQAError("Session başlatılmadı")
        await self.page.bring_to_front()
        await self.page.locator(selector).wait_for(state="visible")
        value = await self.page.evaluate(PLAYBACK_PROBE, {"selector": selector, "sampleMs": sample_ms})
        report = PlaybackReport.from_mapping(value)
        report.assert_healthy()
        return report

    def assert_telemetry_observed(self, endpoint_pattern: str) -> None:
        matcher = re.compile(endpoint_pattern)
        if not any(matcher.search(url) for url in self.observed_requests):
            raise MediaQAError(f"Beklenen telemetry isteği gözlenmedi: {endpoint_pattern}")

    async def save_storage_state(self) -> None:
        if not self.context or not self.storage_state:
            return
        self.storage_state.parent.mkdir(parents=True, exist_ok=True)
        await self.context.storage_state(path=str(self.storage_state))
        try:
            os.chmod(self.storage_state, 0o600)
        except OSError:
            pass

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if not self.context:
            return
        if self.page and not self.page.is_closed():
            await self.page.screenshot(path=str(self.artifacts.screenshot), full_page=True)
        await self.context.tracing.stop(path=str(self.artifacts.trace))
        await self.context.close()


class BrowserPool:
    def __init__(self, playwright: Playwright, max_concurrency: int = 3):
        if max_concurrency < 1:
            raise MediaQAError("Concurrency en az 1 olmalı")
        self.playwright = playwright
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.browsers: dict[str, Browser] = {}

    async def start(self, profiles: Iterable[BrowserProfile]) -> None:
        for name in {profile.browser for profile in profiles}:
            browser_type = getattr(self.playwright, name)
            self.browsers[name] = await browser_type.launch(headless=False)

    async def session(
        self,
        profile: BrowserProfile,
        artifact_root: Path,
        allowed_hosts: Iterable[str],
        storage_state: Path | None = None,
    ):
        if profile.browser not in self.browsers:
            raise MediaQAError(f"Tarayıcı havuzu başlatılmadı: {profile.browser}")
        return BrowserSession(
            self.browsers[profile.browser], profile, artifact_root,
            allowed_hosts, storage_state,
        )

    async def close(self) -> None:
        for browser in self.browsers.values():
            await browser.close()
        self.browsers.clear()
