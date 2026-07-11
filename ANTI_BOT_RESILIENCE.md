# Defensive anti-bot resilience lab

This extension measures whether an owned WAF or anomaly detector separates labelled automation, normal desktop controls, and internally inconsistent clients. It does not impersonate real users or conceal automation.

## What it provides

- Deterministic, labelled client observations for false-positive and false-negative tests.
- Explainable baseline scoring with evidence labels.
- Read-only browser evidence collection for WebDriver exposure, Chrome-runtime consistency, WebGL identity, Canvas and Audio digests, font surface, and user agent.
- Atomic JSON reports suitable for CI comparison.
- JA4 labels as supplied test metadata only. It does not modify TLS handshakes, cipher ordering, HTTP/2 frames, or proxies.

## Use with Playwright

Evaluate `BROWSER_EVIDENCE_SCRIPT` on an explicitly authorized test page, combine the returned evidence with TLS/JA4 labels exported by your own WAF, then construct `ClientObservation`. Never use the collector to alter page APIs or submit synthetic platform analytics.

```bash
python -m py_compile antibot_resilience.py antibot_resilience_smoke.py
python antibot_resilience_smoke.py
```
