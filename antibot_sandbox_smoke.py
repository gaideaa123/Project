from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from antibot_sandbox import (
    SandboxConfig,
    SandboxError,
    _write_report,
    build_synthetic_init_script,
)


class ConfigTests(unittest.TestCase):
    def test_loopback_targets_are_allowed(self):
        SandboxConfig("http://127.0.0.1:8765/").validate()
        SandboxConfig("http://localhost:8765/", mode="synthetic").validate()
        SandboxConfig("http://[::1]:8765/").validate()

    def test_public_and_tls_targets_are_rejected(self):
        for target in ("https://example.com", "http://192.168.1.20", "file:///tmp/test"):
            with self.subTest(target=target), self.assertRaises(SandboxError):
                SandboxConfig(target).validate()

    def test_only_loopback_proxy_is_allowed(self):
        SandboxConfig(proxy="http://127.0.0.1:8899").validate()
        with self.assertRaises(SandboxError):
            SandboxConfig(proxy="http://corp-proxy.example:8080").validate()


class HookTests(unittest.TestCase):
    def test_hook_contains_all_three_runtime_fixtures(self):
        script = build_synthetic_init_script("stable-seed")
        self.assertIn("navigatorPrototype, 'webdriver'", script)
        self.assertIn("window, 'chrome'", script)
        self.assertIn("__sandboxCdpProbe", script)
        self.assertIn("HTMLCanvasElement.prototype, 'toDataURL'", script)
        self.assertIn("WebGLRenderingContext", script)

    def test_seed_is_reproducible(self):
        self.assertEqual(
            build_synthetic_init_script("same"),
            build_synthetic_init_script("same"),
        )
        self.assertNotEqual(
            build_synthetic_init_script("first"),
            build_synthetic_init_script("second"),
        )

    def test_atomic_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "report.json"
            _write_report(target, {"mode": "baseline"})
            self.assertIn('"baseline"', target.read_text(encoding="utf-8"))
            self.assertFalse(target.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
