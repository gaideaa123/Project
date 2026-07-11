from __future__ import annotations

"""Small unit suite that does not require Chrome, FFmpeg or live TikTok."""

import unittest
from unittest.mock import patch

import tiktok_login


class Context:
    def __init__(self, cookies=None):
        self.rows = list(cookies or [])
        self.added = []

    def cookies(self, urls=None):
        return list(self.rows)

    def add_cookies(self, rows):
        self.added.extend(rows)


class SessionBootstrapTests(unittest.TestCase):
    def test_existing_sessionid_is_not_overwritten(self):
        context = Context([{"name": "sessionid", "value": "current"}])
        with patch.object(tiktok_login, "load_session", return_value="stored"):
            self.assertFalse(tiktok_login.bootstrap_session(context, "p"))
        self.assertEqual(context.added, [])

    def test_existing_sessionid_ss_is_not_overwritten(self):
        context = Context([{"name": "sessionid_ss", "value": "current"}])
        with patch.object(tiktok_login, "load_session", return_value="stored"):
            self.assertFalse(tiktok_login.bootstrap_session(context, "p"))
        self.assertEqual(context.added, [])

    def test_empty_profile_is_bootstrapped_once(self):
        context = Context()
        with patch.object(tiktok_login, "load_session", return_value="stored-session"):
            self.assertTrue(tiktok_login.bootstrap_session(context, "p"))
        self.assertEqual(len(context.added), 1)
        self.assertEqual(context.added[0]["value"], "stored-session")

    def test_missing_secret_does_not_add_cookie(self):
        context = Context()
        with patch.object(tiktok_login, "load_session", return_value=""):
            self.assertFalse(tiktok_login.bootstrap_session(context, "p"))
        self.assertEqual(context.added, [])

    def test_cookie_read_errors_fail_closed_to_bootstrap_decision(self):
        context = Context()
        context.cookies = unittest.mock.MagicMock(side_effect=tiktok_login.PlaywrightError("read failed"))
        with patch.object(tiktok_login, "load_session", return_value="stored"):
            self.assertTrue(tiktok_login.bootstrap_session(context, "p"))
        self.assertEqual(len(context.added), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
