import unittest
from unittest.mock import patch

import user_assisted_playwright as runner


class FakePage:
    def __init__(self):
        self.default_timeout = None
        self.navigation_timeout = None

    def set_default_timeout(self, value):
        self.default_timeout = value

    def set_default_navigation_timeout(self, value):
        self.navigation_timeout = value


class FakeContext:
    def __init__(self):
        self.page = FakePage()
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self):
        self.context = FakeContext()
        self.context_options = None
        self.closed = False

    def new_context(self, **kwargs):
        self.context_options = kwargs
        return self.context

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self):
        self.browser = FakeBrowser()
        self.launch_options = None

    def launch(self, **kwargs):
        self.launch_options = kwargs
        return self.browser


class FakePlaywrightContextManager:
    def __init__(self):
        self.chromium = FakeChromium()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class AssistedRunnerTests(unittest.TestCase):
    def test_session_uses_consistent_context_and_closes_resources(self):
        fake = FakePlaywrightContextManager()
        with (
            patch.object(runner, "sync_playwright", return_value=fake),
            patch.object(runner, "wait_for_user_assisted_page") as navigate,
            patch.object(runner, "human_typing") as typing,
            patch.object(runner, "human_mouse_move_and_click") as click,
        ):
            runner.run_assisted_session(
                url="https://example.test/upload",
                text_selector="#caption",
                text="Türkçe test",
                click_selector="#continue",
                wait_for_enter=False,
            )

        browser = fake.chromium.browser
        self.assertEqual(fake.chromium.launch_options, {"headless": False})
        self.assertEqual(browser.context_options["viewport"], {"width": 1280, "height": 720})
        self.assertEqual(browser.context_options["timezone_id"], "Europe/Istanbul")
        self.assertEqual(browser.context.page.default_timeout, 20_000)
        self.assertEqual(browser.context.page.navigation_timeout, 60_000)
        navigate.assert_called_once_with(
            browser.context.page,
            "https://example.test/upload",
            timeout_ms=60_000,
        )
        typing.assert_called_once_with(browser.context.page, "#caption", "Türkçe test")
        click.assert_called_once_with(browser.context.page, "#continue")
        self.assertTrue(browser.context.closed)
        self.assertTrue(browser.closed)

    def test_user_confirmation_happens_before_actions(self):
        fake = FakePlaywrightContextManager()
        events = []
        with (
            patch.object(runner, "sync_playwright", return_value=fake),
            patch.object(runner, "wait_for_user_assisted_page"),
            patch.object(
                runner, "human_typing", side_effect=lambda *args: events.append("type")
            ),
            patch.object(
                runner,
                "human_mouse_move_and_click",
                side_effect=lambda *args: events.append("click"),
            ),
            patch("builtins.input", side_effect=lambda prompt: events.append("prompt")),
        ):
            runner.run_assisted_session(
                text_selector="#caption",
                text="test",
                click_selector="#continue",
            )

        self.assertEqual(events, ["prompt", "type", "click", "prompt"])

    def test_browser_closes_when_context_creation_fails(self):
        fake = FakePlaywrightContextManager()
        browser = fake.chromium.browser

        def fail_context(**kwargs):
            raise RuntimeError("context failed")

        browser.new_context = fail_context
        with patch.object(runner, "sync_playwright", return_value=fake):
            with self.assertRaises(RuntimeError):
                runner.run_assisted_session(wait_for_enter=False)

        self.assertTrue(browser.closed)

    def test_text_selector_and_text_must_be_supplied_together(self):
        with self.assertRaises(ValueError):
            runner.run_assisted_session(
                text_selector="#caption",
                wait_for_enter=False,
            )

    def test_empty_selectors_are_rejected(self):
        with self.assertRaises(ValueError):
            runner.run_assisted_session(
                text_selector=" ",
                text="test",
                wait_for_enter=False,
            )
        with self.assertRaises(ValueError):
            runner.run_assisted_session(
                click_selector=" ",
                wait_for_enter=False,
            )


if __name__ == "__main__":
    unittest.main()
