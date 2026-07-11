import random
import unittest

from utils.antibot_resilience import InteractionConfig, PointerState
from utils.antibot_resilience import human_mouse_move_and_click, human_typing
from utils.network_identity import build_context_options


class FakeKeyboard:
    def __init__(self):
        self.events = []

    def insert_text(self, value):
        self.events.append(("text", value))

    def press(self, value):
        self.events.append(("press", value))


class FakeMouse:
    def __init__(self):
        self.moves = []
        self.events = []

    def move(self, x, y):
        self.moves.append((x, y))

    def down(self):
        self.events.append("down")

    def up(self):
        self.events.append("up")


class FakeLocator:
    def __init__(self, box):
        self.box = box
        self.clicks = 0
        self.waits = []

    def wait_for(self, **kwargs):
        self.waits.append(kwargs)

    def click(self, **kwargs):
        self.clicks += 1

    def bounding_box(self, **kwargs):
        return self.box


class FakePage:
    def __init__(self, box=None):
        self.keyboard = FakeKeyboard()
        self.mouse = FakeMouse()
        self.target = FakeLocator(box)
        self.waited = []

    def locator(self, selector):
        self.selector = selector
        return self.target

    def wait_for_timeout(self, milliseconds):
        self.waited.append(milliseconds)


class InteractionTests(unittest.TestCase):
    def test_typing_supports_unicode_and_control_characters(self):
        page = FakePage()
        cfg = InteractionConfig(
            min_key_delay_ms=1,
            max_key_delay_ms=1,
            pause_probability=0,
        )
        human_typing(page, "#caption", "İyi!\n\t", config=cfg, rng=random.Random(1))
        self.assertEqual(
            page.keyboard.events,
            [("text", "İ"), ("text", "y"), ("text", "i"), ("text", "!"),
             ("press", "Enter"), ("press", "Tab")],
        )
        self.assertEqual(page.target.clicks, 1)

    def test_mouse_curve_ends_inside_target_and_releases_button(self):
        page = FakePage({"x": 100, "y": 50, "width": 80, "height": 40})
        cfg = InteractionConfig(
            min_mouse_steps=5,
            max_mouse_steps=5,
            min_pre_click_ms=0,
            max_pre_click_ms=0,
            min_hold_ms=0,
            max_hold_ms=0,
        )
        state = human_mouse_move_and_click(
            page, "button", pointer=PointerState(10, 10), config=cfg,
            rng=random.Random(2),
        )
        self.assertEqual(len(page.mouse.moves), 5)
        self.assertEqual(page.mouse.events, ["down", "up"])
        self.assertGreaterEqual(state.x, 116)
        self.assertLessEqual(state.x, 164)
        self.assertGreaterEqual(state.y, 58)
        self.assertLessEqual(state.y, 82)

    def test_missing_box_falls_back_to_locator_click(self):
        page = FakePage(None)
        state = human_mouse_move_and_click(page, "button", pointer=PointerState(3, 4))
        self.assertEqual(page.target.clicks, 1)
        self.assertEqual((state.x, state.y), (3, 4))

    def test_context_options_are_consistent(self):
        options = build_context_options(width=1280, height=720)
        self.assertEqual(options["viewport"], options["screen"])
        self.assertEqual(options["timezone_id"], "Europe/Istanbul")


if __name__ == "__main__":
    unittest.main()
