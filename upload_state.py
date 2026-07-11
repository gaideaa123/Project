from __future__ import annotations

"""Visibility-scoped TikTok upload failure and retry handling."""

import re
from dataclasses import dataclass

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

FAILURE = re.compile(
 r"video yüklenemedi|yükleme başarısız|video işlenemedi|desteklenmeyen (?:dosya|format)|"
 r"failed to upload|upload failed|couldn.t upload|unable to upload|unsupported (?:file|format)", re.I,
)
RETRY = re.compile(r"^(daha sonra tekrar deneyin|tekrar dene|yeniden dene|try again|retry)$", re.I)
SELECTORS = (
 '[role="alert"]', '[aria-live="assertive"]', '[data-e2e*="error" i]',
 '[class*="error" i]', '[class*="toast" i]', '[class*="notice" i]', '[class*="message" i]',
)
CLICKABLE = "button, [role='button'], [tabindex='0']"

@dataclass(frozen=True)
class VisibleFailure:
 text: str
 selector: str
 container: object

def _normalize(value: str) -> str:
 return re.sub(r"\s+", " ", value or "").strip()

def visible_upload_failure(page) -> VisibleFailure | None:
 seen: set[str] = set()
 for selector in SELECTORS:
  locators = page.locator(selector)
  try: count = min(locators.count(), 60)
  except PlaywrightError: continue
  for index in range(count):
   locator = locators.nth(index)
   try:
    if not locator.is_visible(timeout=120): continue
    text = _normalize(locator.inner_text(timeout=500)); match = FAILURE.search(text)
    if not match: continue
    key = text.casefold()
    if key in seen: continue
    seen.add(key); return VisibleFailure(text or match.group(0), selector, locator)
   except (PlaywrightTimeout, PlaywrightError): continue
 return None

def _label(locator) -> str:
 try: return _normalize(locator.get_attribute("aria-label") or locator.inner_text(timeout=400) or "")
 except (PlaywrightTimeout, PlaywrightError): return ""

def _click(locator, page) -> bool:
 try: locator.scroll_into_view_if_needed(timeout=2000)
 except (AttributeError, PlaywrightError): pass
 try: locator.click(timeout=4000); return True
 except PlaywrightError:
  try: locator.click(timeout=4000, force=True); return True
  except PlaywrightError:
   try:
    box=locator.bounding_box(timeout=1200)
    if not box:return False
    page.mouse.click(box["x"]+box["width"]/2,box["y"]+box["height"]/2);return True
   except (AttributeError,PlaywrightError):return False

def click_retry(page, failure: VisibleFailure) -> bool:
 """Click only the retry control associated with the verified visible error."""
 scopes=[failure.container]
 try:
  for depth in range(1,7): scopes.append(failure.container.locator(f"xpath=ancestor::*[{depth}]"))
 except (AttributeError,PlaywrightError): pass
 for scope in scopes:
  try:
   role=scope.get_by_role("button",name=RETRY)
   if role.count() and role.first.is_visible(timeout=250) and _click(role.first,page):return True
   candidates=scope.locator(CLICKABLE)
   for index in range(min(candidates.count(),40)):
    candidate=candidates.nth(index)
    if RETRY.fullmatch(_label(candidate)) and candidate.is_visible(timeout=200) and _click(candidate,page):return True
  except (PlaywrightTimeout,PlaywrightError):continue
 return False

def selected_file(page) -> tuple[str,int] | None:
 input_locator=page.locator('input[type="file"]')
 try:
  if not input_locator.count():return None
  value=input_locator.first.evaluate("el => el.files && el.files.length ? [el.files[0].name, el.files[0].size] : null")
  return (str(value[0]),int(value[1])) if value else None
 except (PlaywrightError,TypeError,ValueError):return None
