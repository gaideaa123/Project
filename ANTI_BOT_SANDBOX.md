# PR #39 executable anti-bot education sandbox

This PoC turns the labelled observations from PR #39 into a runnable, **loopback-only** comparison lab. It refuses HTTPS, LAN/public hosts, and non-loopback proxies by construction.

## What is implemented

- **Runtime cohort hook:** a Playwright `BrowserContext.add_init_script()` fixture changes the lab-visible `navigator.webdriver` prototype value, supplies a labelled `window.chrome` mock, and exposes a deterministic stack-getter probe for CDP leak telemetry.
- **Synthetic hardware cohort:** deterministic Canvas `toDataURL()` pixel noise plus WebGL vendor/renderer fixtures. The same seed gives the same classroom result.
- **Network cohort:** labelled HTTP headers and an optional loopback HTTP/SOCKS5 proxy. Playwright does not expose HTTP/2 pseudo-header order, TLS ClientHello, or JA4 construction, so the PoC does not pretend to configure them.
- **PR #39 integration:** browser evidence is converted into `ClientObservation` and scored by `DefensiveDetector`.

## Run

```bash
pip install -r requirements.txt
playwright install chromium
python antibot_sandbox.py --serve --mode baseline --output baseline.json
python antibot_sandbox.py --serve --mode synthetic --seed classroom-1 --output synthetic.json
python antibot_sandbox_smoke.py
```

Use `--headed` to watch the browser. A local proxy can be supplied only when it is bound to loopback:

```bash
python antibot_sandbox.py --serve --mode synthetic --proxy http://127.0.0.1:8899
```

The built-in server is intentionally plain local HTTP, therefore TLS/JA4 is reported as not applicable. For TLS lessons, export labelled JA4 observations from an independently owned WAF fixture and feed those labels into PR #39's existing `ClientObservation`; do not infer or fabricate them.

## Guardrails

The runner contains no `--disable-blink-features=AutomationControlled`, no CDP concealment, no TLS impersonation, and no ISP/upstream proxy support. Those would turn a detector-validation fixture into a transferable evasion client. The synthetic mode is still useful for training because engineers can observe exactly how detector scores change when browser-visible evidence is inconsistent.
