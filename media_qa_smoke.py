from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from media_qa import (
    BrowserProfile,
    DeterministicInput,
    MediaQAError,
    PlaybackReport,
    SessionArtifacts,
)


class BrowserProfileTests(unittest.TestCase):
    def test_valid_profile(self):
        BrowserProfile().validate()

    def test_invalid_browser(self):
        with self.assertRaises(MediaQAError):
            BrowserProfile(browser="stealth").validate()

    def test_small_viewport_rejected(self):
        with self.assertRaises(MediaQAError):
            BrowserProfile(width=640, height=480).validate()


class InputTests(unittest.TestCase):
    def test_seed_is_reproducible_and_ends_at_target(self):
        first = DeterministicInput("run-42").bezier_points((0, 0), (100, 50))
        second = DeterministicInput("run-42").bezier_points((0, 0), (100, 50))
        self.assertEqual(first, second)
        self.assertAlmostEqual(first[-1][0], 100)
        self.assertAlmostEqual(first[-1][1], 50)

    def test_too_few_steps_rejected(self):
        with self.assertRaises(MediaQAError):
            DeterministicInput("x").bezier_points((0, 0), (1, 1), 1)


class PlaybackTests(unittest.TestCase):
    def healthy(self) -> PlaybackReport:
        return PlaybackReport(
            visible=True, intersection_ratio=1.0, ready_state=4,
            network_state=1, start_time=0.0, current_time=3.0,
            advanced_by=3.0, presented_frames=60, dropped_frames=0,
            decoded_width=1080, decoded_height=1920,
            buffered_seconds=10.0, paused=False, ended=False,
        )

    def test_healthy_report(self):
        self.healthy().assert_healthy()

    def test_zero_progress_rejected(self):
        value = self.healthy().__dict__ | {"advanced_by": 0.0}
        with self.assertRaises(MediaQAError):
            PlaybackReport(**value).assert_healthy()

    def test_non_visible_video_rejected(self):
        value = self.healthy().__dict__ | {"visible": False, "intersection_ratio": 0.0}
        with self.assertRaises(MediaQAError):
            PlaybackReport(**value).assert_healthy()


class ArtifactTests(unittest.TestCase):
    def test_unique_atomic_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = SessionArtifacts(Path(temporary), "run-a")
            report = PlaybackTests().healthy()
            artifacts.write_report(report, {"browser": "chromium"})
            self.assertTrue(artifacts.result.is_file())
            self.assertIn('"advanced_by": 3.0', artifacts.result.read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                SessionArtifacts(Path(temporary), "run-a")


if __name__ == "__main__":
    unittest.main(verbosity=2)
