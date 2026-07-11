from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from antibot_resilience import (
    DefensiveDetector,
    LabelledFixtureFactory,
    ResilienceError,
    ResilienceReport,
)
from antibot_sandbox import SandboxConfig, SandboxError, build_synthetic_init_script


class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.factory = LabelledFixtureFactory("stable-seed")
        self.detector = DefensiveDetector()

    def test_known_automation_is_detected(self):
        result = self.detector.score(self.factory.build("run-1", "known-automation"))
        self.assertTrue(result.suspicious)
        self.assertIn("webdriver-exposed", result.labels)

    def test_desktop_control_is_not_detected(self):
        result = self.detector.score(self.factory.build("run-2", "desktop-control"))
        self.assertFalse(result.suspicious)

    def test_inconsistent_client_is_detected(self):
        result = self.detector.score(self.factory.build("run-3", "inconsistent-client"))
        self.assertTrue(result.suspicious)
        self.assertIn("chrome-runtime-mismatch", result.labels)

    def test_fixture_is_reproducible(self):
        self.assertEqual(
            self.factory.build("same", "desktop-control"),
            LabelledFixtureFactory("stable-seed").build("same", "desktop-control"),
        )

    def test_unknown_cohort_rejected(self):
        with self.assertRaises(ResilienceError):
            self.factory.build("run", "stealth")

    def test_atomic_report(self):
        observations = [
            self.factory.build("a", "known-automation"),
            self.factory.build("b", "desktop-control"),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "report.json"
            ResilienceReport(self.detector).write(target, observations)
            text = target.read_text(encoding="utf-8")
            self.assertIn('"detection_rate": 0.5', text)
            self.assertFalse(target.with_suffix(".json.tmp").exists())


class SandboxGuardrailTests(unittest.TestCase):
    def test_only_loopback_http_targets_are_accepted(self):
        SandboxConfig("http://127.0.0.1:8765/", mode="synthetic").validate()
        for target in ("https://example.com", "http://192.168.1.10", "file:///tmp/lab"):
            with self.subTest(target=target), self.assertRaises(SandboxError):
                SandboxConfig(target, mode="synthetic").validate()

    def test_non_loopback_proxy_is_rejected(self):
        SandboxConfig(proxy="http://127.0.0.1:8899").validate()
        with self.assertRaises(SandboxError):
            SandboxConfig(proxy="http://proxy.example:8080").validate()

    def test_runtime_hook_is_executable_and_deterministic(self):
        first = build_synthetic_init_script("classroom")
        second = build_synthetic_init_script("classroom")
        self.assertEqual(first, second)
        self.assertRegex(first, r"\}\)\(\d+\);\s*$")
        self.assertNotIn("__SEED__", first)
        for marker in (
            "navigatorPrototype, 'webdriver'",
            "window, 'chrome'",
            "__sandboxCdpProbe",
            "HTMLCanvasElement.prototype, 'toDataURL'",
            "WebGLRenderingContext",
        ):
            self.assertIn(marker, first)


if __name__ == "__main__":
    unittest.main(verbosity=2)
