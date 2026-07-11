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


if __name__ == "__main__":
    unittest.main(verbosity=2)
