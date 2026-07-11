# High-fidelity media QA

`media_qa.py` provides isolated Playwright browser sessions, deterministic input scenarios, real video decode/render checks, request observation, storage-state separation, traces, screenshots, and atomic JSON reports.

It deliberately does not spoof browser fingerprints, hide WebDriver/CDP, alter TLS/JA4, or inject fake analytics. Run it only against owned or explicitly authorized hosts; `BrowserSession.goto()` enforces an allowlist and marks requests with `X-Test-Run-ID` and `X-Automation-Purpose: media-qa`.

## Minimal usage

```python
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from media_qa import BrowserPool, BrowserProfile

async def main():
    profile = BrowserProfile(browser="chromium")
    async with async_playwright() as playwright:
        pool = BrowserPool(playwright, max_concurrency=2)
        await pool.start([profile])
        session = await pool.session(
            profile,
            artifact_root=Path("qa-artifacts"),
            allowed_hosts={"staging.example.com"},
            storage_state=Path(".qa-state/account-1.json"),
        )
        async with session:
            await session.goto("https://staging.example.com/media/1")
            report = await session.probe_playback("video", sample_ms=4000)
            session.assert_telemetry_observed(r"/internal-test-metrics/playback")
            session.artifacts.write_report(report, {
                "browser": profile.browser,
                "run_id": session.run_id,
            })
            await session.save_storage_state()
        await pool.close()

asyncio.run(main())
```

## Validation

```bash
python -m py_compile media_qa.py media_qa_smoke.py
python media_qa_smoke.py
```

For full browser runs, install browsers first with `playwright install chromium firefox webkit`. Keep `.qa-state/` and `qa-artifacts/` out of source control because storage-state files can contain authentication material.
