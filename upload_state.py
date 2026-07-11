from __future__ import annotations

"""Visibility-scoped TikTok upload state detection.

TikTok keeps translated error templates in the DOM even when they are hidden.
Never classify body.inner_text alone as an active upload failure.
"""

import re
from dataclasses import dataclass

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

FAILURE = re.compile(
 r"video yüklenemedi|yükleme başarısız|video işlenemedi|desteklenmeyen (?:dosya|format)|"
 r"failed to upload|upload failed|couldn.t upload|unable to upload|unsupported (?:file|format)",
 re.I,
)
SELECTORS = (
 '[role="alert"]', '[aria-live="assertive"]', '[data-e2e*="error" i]',
 '[class*="error" i]', '[class*="toast" i]', '[class*="notice" i]',
 '[class*="message" i]',
)

@dataclass(frozen=True)
class VisibleFailure:
 text: str
 selector: str

def _normalize(value: str) -> str:
 return re.sub(r"\s+", " ", value or "").strip()

def visible_upload_failure(page) -> VisibleFailure | None:
 """Return an error only when its rendered element is currently visible."""
 seen: set[str] = set()
 for selector in SELECTORS:
  locators = page.locator(selector)
  try:
   count = min(locators.count(), 60)
  except PlaywrightError:
   continue
  for index in range(count):
   locator = locators.nth(index)
   try:
    if not locator.is_visible(timeout=120):
     continue
    text = _normalize(locator.inner_text(timeout=500))
    match = FAILURE.search(text)
    if not match:
     continue
    key = text.casefold()
    if key in seen:
     continue
    seen.add(key)
    return VisibleFailure(text or match.group(0), selector)
   except (PlaywrightTimeout, PlaywrightError):
    continue
 return None

def selected_file(page) -> tuple[str, int] | None:
 """Return selected file name and size when the input is still inspectable."""
 input_locator = page.locator('input[type="file"]')
 try:
  if not input_locator.count():
   return None
  value = input_locator.first.evaluate(
   "el => el.files && el.files.length ? [el.files[0].name, el.files[0].size] : null"
  )
  if not value:
   return None
  return str(value[0]), int(value[1])
 except (PlaywrightError, TypeError, ValueError):
  return None
