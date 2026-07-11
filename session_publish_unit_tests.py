from __future__ import annotations

"""Session bootstrap tests without Chrome or live TikTok."""

import unittest
from unittest.mock import MagicMock, patch

import tiktok_login


class Context:
 def __init__(self, cookies=None):
  self.rows = list(cookies or [])
  self.added = []
  self.cleared = []

 def cookies(self, urls=None):
  installed = {row["name"]: row for row in self.rows}
  installed.update({row["name"]: row for row in self.added})
  return list(installed.values())

 def clear_cookies(self, name=None):
  self.cleared.append(name)
  self.rows = [row for row in self.rows if row.get("name") != name]

 def add_cookies(self, rows):
  self.added.extend(rows)


class SessionBootstrapTests(unittest.TestCase):
 def test_matching_session_is_not_reinstalled_without_force(self):
  context = Context([{"name": "sessionid", "value": "stored-session-value"}])
  with patch.object(tiktok_login, "load_session", return_value="stored-session-value"):
   self.assertFalse(tiktok_login.bootstrap_session(context, "p"))
  self.assertEqual(context.added, [])

 def test_empty_profile_installs_both_cookie_aliases(self):
  context = Context()
  with patch.object(tiktok_login, "load_session", return_value="stored-session-value"):
   self.assertTrue(tiktok_login.bootstrap_session(context, "p"))
  self.assertEqual({row["name"] for row in context.added}, {"sessionid", "sessionid_ss"})
  self.assertTrue(all(row["sameSite"] == "None" for row in context.added))

 def test_force_replaces_stale_persistent_profile_cookies(self):
  context = Context([{"name": "sessionid", "value": "old"}, {"name": "sessionid_ss", "value": "old"}])
  with patch.object(tiktok_login, "load_session", return_value="new-session-value"):
   self.assertTrue(tiktok_login.bootstrap_session(context, "p", force=True))
  self.assertEqual(context.cleared, ["sessionid", "sessionid_ss"])
  self.assertEqual({row["value"] for row in context.added}, {"new-session-value"})

 def test_missing_secret_does_not_add_cookie(self):
  context = Context()
  with patch.object(tiktok_login, "load_session", return_value=""):
   self.assertFalse(tiktok_login.bootstrap_session(context, "p"))
  self.assertEqual(context.added, [])

 def test_cookie_read_error_still_installs_session(self):
  context = Context()
  context.cookies = MagicMock(side_effect=tiktok_login.PlaywrightError("read failed"))
  with patch.object(tiktok_login, "load_session", return_value="stored-session-value"):
   self.assertTrue(tiktok_login.bootstrap_session(context, "p"))
  self.assertEqual(len(context.added), 2)

 def test_parser_accepts_sessionid_ss_cookie_line(self):
  self.assertEqual(
   tiktok_login._session_value("sessionid_ss=abcdefghijklmnop; Path=/"),
   "abcdefghijklmnop",
  )


if __name__ == "__main__":
 unittest.main(verbosity=2)
