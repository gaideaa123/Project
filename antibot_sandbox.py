from __future__ import annotations

"""Loopback-only anti-bot signal laboratory for PR #39.

The module deliberately refuses public targets and non-loopback proxies. It lets
engineers compare an unmodified Playwright context with a deterministic synthetic
cohort on a local training page. It is a detector-validation fixture, not a
stealth browser or a production traffic client.
"""

import argparse
import hashlib
import json
import threading
import uuid
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from antibot_resilience import BROWSER_EVIDENCE_SCRIPT, ClientObservation, DefensiveDetector


class SandboxError(RuntimeError):
    pass


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host.casefold() == "localhost":
        return True
    try:
        return ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class SandboxConfig:
    target: str = "http://127.0.0.1:8765/"
    seed: str = "pr39-training"
    mode: str = "baseline"
    proxy: str | None = None
    headless: bool = True

    def validate(self) -> None:
        target = urlparse(self.target)
        if target.scheme != "http" or not _is_loopback(target.hostname):
            raise SandboxError("sandbox hedefi yalnız loopback üzerindeki http URL olabilir")
        if self.mode not in {"baseline", "synthetic"}:
            raise SandboxError("mode baseline veya synthetic olmalı")
        if not self.seed.strip():
            raise SandboxError("seed boş olamaz")
        if self.proxy:
            parsed_proxy = urlparse(self.proxy)
            if parsed_proxy.scheme not in {"http", "socks5"} or not _is_loopback(parsed_proxy.hostname):
                raise SandboxError("yalnız laboratuvar makinesindeki loopback proxy kabul edilir")


# This hook is installed only after SandboxConfig has rejected every non-loopback
# target. The deterministic seed makes classroom observations reproducible.
def build_synthetic_init_script(seed: str) -> str:
    seed_number = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:4], "big")
    body = r"""
((seed) => {
  'use strict';
  const marker = Object.freeze({purpose: 'authorized-local-sandbox', seed});
  Object.defineProperty(window, '__ANTI_BOT_SANDBOX__', {value: marker});

  // Runtime cohort: model the values a detector might encounter. We patch the
  // Navigator prototype rather than one object so prototype checks are visible.
  const navigatorPrototype = Object.getPrototypeOf(navigator);
  Object.defineProperty(navigatorPrototype, 'webdriver', {
    configurable: true,
    enumerable: true,
    get: () => false
  });
  const chromeMock = Object.freeze({
    app: Object.freeze({isInstalled: false}),
    runtime: Object.freeze({id: undefined}),
    sandboxMarker: true
  });
  try {
    Object.defineProperty(window, 'chrome', {
      configurable: true,
      value: chromeMock
    });
  } catch (_error) {
    // A browser may expose a non-configurable object. Keep the lab explicit
    // rather than weakening the descriptor with additional concealment tricks.
    window.__ANTI_BOT_SANDBOX_CHROME_MOCK_FAILED__ = true;
  }

  // CDP/runtime leak fixture. Calling this function deterministically exercises
  // a stack getter, allowing a detector lab to verify getter-access telemetry.
  let cdpStackReads = 0;
  Object.defineProperty(window, '__sandboxCdpProbe', {
    value: () => {
      const sample = new Error('sandbox-cdp-probe');
      Object.defineProperty(sample, 'stack', {
        configurable: true,
        get: () => { cdpStackReads += 1; return 'sandbox-cdp-stack'; }
      });
      void sample.stack;
      return cdpStackReads;
    }
  });

  // Small deterministic PRNG. It never uses time or system entropy, so two runs
  // with the same seed produce the same classroom evidence.
  let state = seed >>> 0;
  const nextByte = () => {
    state ^= state << 13; state ^= state >>> 17; state ^= state << 5;
    return state & 0xff;
  };

  const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
  Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', {
    configurable: true,
    value: function(...args) {
      const context = this.getContext('2d');
      if (!context || this.width < 1 || this.height < 1) {
        return originalToDataURL.apply(this, args);
      }
      const pixel = context.getImageData(0, 0, 1, 1);
      const original = new Uint8ClampedArray(pixel.data);
      pixel.data[0] = (pixel.data[0] + 1 + (nextByte() % 2)) & 0xff;
      context.putImageData(pixel, 0, 0);
      try {
        return originalToDataURL.apply(this, args);
      } finally {
        pixel.data.set(original);
        context.putImageData(pixel, 0, 0);
      }
    }
  });

  const patchWebGL = prototype => {
    if (!prototype) return;
    const original = prototype.getParameter;
    Object.defineProperty(prototype, 'getParameter', {
      configurable: true,
      value: function(parameter) {
        if (parameter === 0x9245) return `Sandbox Vendor ${seed % 97}`;
        if (parameter === 0x9246) return `Sandbox Renderer ${seed % 193}`;
        return original.call(this, parameter);
      }
    });
  };
  patchWebGL(window.WebGLRenderingContext?.prototype);
  patchWebGL(window.WebGL2RenderingContext?.prototype);
})(__SEED__);
"""
    return body.replace("__SEED__", str(seed_number))


class _TrainingHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _write(self, status: int, content_type: str, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802, stdlib callback name
        if self.path == "/headers":
            body = json.dumps(dict(self.headers.items()), sort_keys=True).encode("utf-8")
            self._write(200, "application/json", body)
            return
        if self.path != "/":
            self._write(404, "text/plain", b"not found")
            return
        body = b"""<!doctype html><meta charset=utf-8><title>PR39 sandbox</title>
<h1>PR #39 local anti-bot signal sandbox</h1>
<canvas id=canvas width=240 height=80></canvas>
<script>
const c = document.querySelector('#canvas').getContext('2d');
c.font = '16px sans-serif'; c.fillText('authorized local sandbox', 4, 28);
</script>"""
        self._write(200, "text/html; charset=utf-8", body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


class LocalTrainingServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        if not _is_loopback(host):
            raise SandboxError("eğitim sunucusu yalnız loopback adresine bağlanabilir")
        self.server = ThreadingHTTPServer((host, port), _TrainingHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "LocalTrainingServer":
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class SandboxRunner:
    def __init__(self, config: SandboxConfig):
        config.validate()
        self.config = config

    def run(self) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise SandboxError("Playwright kurulu değil: pip install -r requirements.txt") from exc

        run_id = uuid.uuid4().hex
        headers = {
            "X-Test-Run-ID": run_id,
            "X-Automation-Purpose": "anti-bot-education",
            "X-Sandbox-Cohort": self.config.mode,
        }
        launch_options: dict[str, Any] = {"headless": self.config.headless}
        if self.config.proxy:
            launch_options["proxy"] = {"server": self.config.proxy}

        with sync_playwright() as playwright:
            # No automation-concealment Chromium flags are used. That keeps this
            # fixture honest and prevents accidental transfer to public targets.
            browser = playwright.chromium.launch(**launch_options)
            context = browser.new_context(extra_http_headers=headers)
            if self.config.mode == "synthetic":
                context.add_init_script(script=build_synthetic_init_script(self.config.seed))
            page = context.new_page()
            page.goto(self.config.target, wait_until="domcontentloaded")
            evidence = page.evaluate(BROWSER_EVIDENCE_SCRIPT)
            cdp_reads = page.evaluate("() => window.__sandboxCdpProbe?.() || 0")
            observed_headers = page.evaluate("async () => (await fetch('/headers')).json()")
            browser.close()

        observation = ClientObservation(
            run_id=run_id,
            tls_family="local-http-no-tls",
            ja4_label="not-applicable-loopback-http",
            webdriver=bool(evidence["webdriver"]),
            chrome_runtime=bool(evidence["chrome_runtime"]),
            notification_permission=str(evidence["notification_permission"]),
            webgl_vendor=str(evidence["webgl_vendor"]),
            webgl_renderer=str(evidence["webgl_renderer"]),
            canvas_digest=str(evidence["canvas_digest"]),
            audio_digest=str(evidence["audio_digest"]),
            font_count=int(evidence["font_count"]),
            user_agent=str(evidence["user_agent"]),
        )
        detection = DefensiveDetector().score(observation)
        return {
            "mode": self.config.mode,
            "observation": asdict(observation),
            "detection": {
                "score": detection.score,
                "labels": list(detection.labels),
                "suspicious": detection.suspicious,
            },
            "runtime": {"cdp_stack_getter_reads": cdp_reads},
            "network": {"observed_headers": observed_headers, "protocol": "local-http"},
        }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="PR #39 loopback-only anti-bot eğitim sandbox'ı")
    parser.add_argument("--mode", choices=("baseline", "synthetic"), default="baseline")
    parser.add_argument("--target", default="http://127.0.0.1:8765/")
    parser.add_argument("--seed", default="pr39-training")
    parser.add_argument("--proxy", help="yalnız loopback laboratuvar proxy URL'si")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--serve", action="store_true", help="yerel eğitim sunucusunu da başlat")
    parser.add_argument("--output", type=Path, default=Path("sandbox-report.json"))
    args = parser.parse_args()
    config = SandboxConfig(args.target, args.seed, args.mode, args.proxy, not args.headed)
    runner = SandboxRunner(config)
    if args.serve:
        parsed = urlparse(args.target)
        with LocalTrainingServer(parsed.hostname or "127.0.0.1", parsed.port or 80):
            report = runner.run()
    else:
        report = runner.run()
    _write_report(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
