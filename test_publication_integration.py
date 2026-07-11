import unittest
from unittest.mock import Mock, patch

import web_upload_engine as engine


class PublicationIntegrationTests(unittest.TestCase):
    def test_guard_runs_before_fresh_button_click_and_verified_receipt(self):
        events = []
        page = Mock()
        stale_button = Mock()
        fresh_button = Mock()
        fresh_button.is_enabled.return_value = True
        fresh_button.click.side_effect = lambda **kwargs: events.append("click")

        with (
            patch.object(engine.publication_guard, "assert_publishable", side_effect=lambda *args: events.append("guard")) as guard,
            patch.object(engine, "publish_button", return_value=fresh_button) as resolve,
            patch.object(engine.publication_guard, "wait_for_verified_publication", side_effect=lambda *args, **kwargs: events.append("verify")) as verify,
        ):
            engine.click_publish_and_verify(page, "profile-a", events.append)

        self.assertEqual(events, ["guard", "Yayınla tıklanıyor", "click", "verify"])
        guard.assert_called_once_with(page, events.append)
        resolve.assert_called_once_with(page)
        fresh_button.scroll_into_view_if_needed.assert_called_once_with()
        fresh_button.click.assert_called_once_with(timeout=10000)
        verify.assert_called_once_with(
            page,
            "profile-a",
            status=events.append,
            timeout_seconds=180,
        )
        stale_button.click.assert_not_called()

    def test_missing_button_fails_closed(self):
        with (
            patch.object(engine.publication_guard, "assert_publishable"),
            patch.object(engine, "publish_button", return_value=None),
        ):
            with self.assertRaisesRegex(engine.WebUploadError, "kayboldu"):
                engine.click_publish_and_verify(Mock(), "profile-a", Mock())

    def test_disabled_button_fails_closed(self):
        button = Mock()
        button.is_enabled.return_value = False
        with (
            patch.object(engine.publication_guard, "assert_publishable"),
            patch.object(engine, "publish_button", return_value=button),
        ):
            with self.assertRaisesRegex(engine.WebUploadError, "devre dışı"):
                engine.click_publish_and_verify(Mock(), "profile-a", Mock())
        button.click.assert_not_called()

    def test_unverified_result_is_propagated_as_upload_error(self):
        button = Mock()
        button.is_enabled.return_value = True
        with (
            patch.object(engine.publication_guard, "assert_publishable"),
            patch.object(engine, "publish_button", return_value=button),
            patch.object(
                engine.publication_guard,
                "wait_for_verified_publication",
                side_effect=RuntimeError("kesin yayın kanıtı yok"),
            ),
        ):
            with self.assertRaisesRegex(engine.WebUploadError, "kesin yayın kanıtı yok"):
                engine.click_publish_and_verify(Mock(), "profile-a", Mock())


if __name__ == "__main__":
    unittest.main()
