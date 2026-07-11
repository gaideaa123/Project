from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import tiktok_login
import tiktok_overlays

class Candidate:
 def __init__(self, label="Aç", inside=True, click_error=False):
  self.label = label; self.inside = inside; self.click_error = click_error; self.clicks = []
 @property
 def first(self): return self
 def count(self): return 1
 def get_attribute(self, name): return self.label if name == "aria-label" else None
 def inner_text(self, timeout=0): return self.label
 def is_visible(self, timeout=0): return True
 def evaluate(self, script): return self.inside
 def scroll_into_view_if_needed(self, timeout=0): pass
 def click(self, **kwargs):
  self.clicks.append(kwargs)
  if self.click_error and not kwargs.get("force"): raise tiktok_overlays.PlaywrightError("intercepted")

class Collection:
 def __init__(self, rows): self.rows = rows
 @property
 def first(self): return self.rows[0]
 def count(self): return len(self.rows)
 def nth(self, index): return self.rows[index]

class Page:
 def __init__(self, rows):
  self.rows = rows; self.frames = []; self.main_frame = self; self.mouse = MagicMock(); self.waits = []
 def locator(self, selector): return Collection(self.rows)
 def wait_for_timeout(self, value): self.waits.append(value)
 def is_closed(self): return False


def main() -> None:
 good = Candidate(click_error=True); unrelated = Candidate(inside=False)
 page = Page([unrelated, good])
 assert tiktok_overlays._click_global_verified_enable(page, page)
 assert good.clicks[-1].get("force") is True
 assert unrelated.clicks == []
 assert tiktok_overlays.CONTENT_CHECK_TEXT.search("Otomatik içerik kontrolleri açılsın mı? Müzik telif hakkı kontrolü İçerik kontrolü (hafif)")

 calls = []
 context = MagicMock()
 context.cookies.return_value = []
 uploader = SimpleNamespace(
  launch_context=lambda playwright, profile: context,
  wait_for_login=lambda page, timeout_seconds=600: calls.append("wait"),
  upload_file=lambda page, video: calls.append("upload"),
  fill_caption=lambda page, caption, timeout_seconds=180: calls.append("caption"),
  prepare_upload=lambda request: None,
 )
 with patch.object(tiktok_login, "load_session", return_value=""), patch.object(tiktok_login.tiktok_overlays, "clear_new_account_overlays") as clear:
  tiktok_login.install(uploader)
  uploader.wait_for_login(page); uploader.upload_file(page, "video.mp4"); uploader.fill_caption(page, "caption")
  assert calls == ["wait", "upload", "caption"]
  assert clear.call_count == 4

 print("OK: İçerik kontrolü Aç doğrulanıyor, force fallback ve uploader aşamaları çalışıyor")

if __name__ == "__main__": main()
