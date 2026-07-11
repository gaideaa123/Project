from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import tiktok_login

class Context:
 def __init__(self, cookies=None):
  self.rows = list(cookies or [])
  self.added = []
  self.cleared = []
  self.closed = False

 def cookies(self, urls=None):
  values = list(self.rows)
  for row in self.added:
   values = [item for item in values if not (item.get("name") == row["name"] and item.get("domain") == row["domain"])]
   values.append(dict(row))
  return values

 def clear_cookies(self, name=None):
  self.cleared.append(name)
  self.rows = [row for row in self.rows if row.get("name") != name]
  self.added = [row for row in self.added if row.get("name") != name]

 def add_cookies(self, rows):
  self.added.extend(rows)

 def close(self):
  self.closed = True

class SessionBootstrapTests(unittest.TestCase):
 def test_stale_persistent_cookies_are_replaced_with_both_aliases(self):
  context = Context([
   {"name": "sessionid", "value": "stale", "domain": ".tiktok.com"},
   {"name": "sessionid_ss", "value": "also-stale", "domain": ".tiktok.com"},
  ])
  with patch.object(tiktok_login, "load_session", return_value="stored-session-value-123"):
   self.assertTrue(tiktok_login.bootstrap_session(context, "p"))
  self.assertEqual(context.cleared, ["sessionid", "sessionid_ss"])
  self.assertEqual({row["name"] for row in context.added}, {"sessionid", "sessionid_ss"})
  self.assertTrue(all(row["sameSite"] == "None" for row in context.added))
  self.assertTrue(all(row["value"] == "stored-session-value-123" for row in context.added))

 def test_missing_secret_does_not_touch_browser(self):
  context = Context()
  with patch.object(tiktok_login, "load_session", return_value=""):
   self.assertFalse(tiktok_login.bootstrap_session(context, "p"))
  self.assertEqual(context.added, [])
  self.assertEqual(context.cleared, [])

 def test_sessionid_ss_cookie_text_is_parsed(self):
  value = tiktok_login._session_value("foo=1; sessionid_ss=abcdefghijklmnop1234; bar=2")
  self.assertEqual(value, "abcdefghijklmnop1234")

 def test_install_succeeds_on_minimal_current_uploader(self):
  context = Context()
  uploader = SimpleNamespace(
   launch_context=MagicMock(return_value=context),
   prepare_upload=lambda request: None,
  )
  with patch.object(tiktok_login, "load_session", return_value="stored-session-value-123"):
   tiktok_login.install(uploader)
   result = uploader.launch_context(object(), "profile")
  self.assertIs(result, context)
  self.assertEqual({row["name"] for row in context.added}, {"sessionid", "sessionid_ss"})
  self.assertTrue(uploader._signaldesk_login_installed)

 def test_cookie_write_failure_closes_context(self):
  context = Context()
  context.add_cookies = MagicMock(side_effect=tiktok_login.PlaywrightError("write failed"))
  uploader = SimpleNamespace(launch_context=MagicMock(return_value=context), prepare_upload=lambda request: None)
  with patch.object(tiktok_login, "load_session", return_value="stored-session-value-123"):
   tiktok_login.install(uploader)
   with self.assertRaises(tiktok_login.LoginError):
    uploader.launch_context(object(), "profile")
  self.assertTrue(context.closed)

if __name__ == "__main__":
 unittest.main(verbosity=2)
