from __future__ import annotations

"""Handle TikTok onboarding while explicitly enabling automatic content checks."""

import re
import time
from collections.abc import Callable

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

StatusCallback = Callable[[str], None]
COOKIE_ALLOW = re.compile(r"^(tümüne izin ver|tüm çerezlere izin ver|çerezlere izin ver|allow all|allow all cookies|accept all|accept all cookies)$", re.I)
CONTENT_CHECK_TEXT = re.compile(
 r"otomatik içerik kontrolleri açılsın mı|müzik telif hakkı kontrolü|"
 r"içerik kontrolü\s*\(hafif\)|içerik kontrol|içeriği kontrol|"
 r"telif hakkı kontrol|automatic content checks|content check|copyright check",
 re.I,
)
ENABLE_CONTENT_CHECK = re.compile(r"^(aç|etkinleştir|kontrolü aç|içerik kontrolünü aç|turn on|enable|enable check|turn on content check)$", re.I)
GOT_IT = re.compile(r"^(anladım|tamam|got it|understood|i understand)$", re.I)
PUBLISH_TEXT = re.compile(r"paylaşmaya devam|publish anyway|share now|post now|hemen paylaş|hemen yayınla|yayınlamaya devam", re.I)
CONTAINER_SELECTORS = (
 '[role="dialog"]', '[aria-modal="true"]', '[role="alertdialog"]',
 '[data-e2e*="modal" i]', '[class*="modal" i]', '[class*="dialog" i]',
 '[class*="popup" i]', '[class*="drawer" i]', '[class*="banner" i]',
 '[class*="cookie" i]',
)
CLICKABLE_SELECTOR = "button, [role='button'], [tabindex='0']"

def _notify(status: StatusCallback | None, message: str) -> None:
 if status:
  status(message)

def _visible(locator, timeout: int = 250) -> bool:
 try:
  return bool(locator.count() and locator.first.is_visible(timeout=timeout))
 except (PlaywrightTimeout, PlaywrightError):
  return False

def _label(locator) -> str:
 try:
  return re.sub(r"\s+", " ", locator.get_attribute("aria-label") or locator.inner_text(timeout=500) or "").strip()
 except (PlaywrightTimeout, PlaywrightError):
  return ""

def _containers(surface):
 seen: set[str] = set()
 for selector in CONTAINER_SELECTORS:
  locators = surface.locator(selector)
  try:
   count = min(locators.count(), 40)
  except PlaywrightError:
   count = 0
  for index in range(count):
   container = locators.nth(index)
   try:
    if not container.is_visible(timeout=150):
     continue
    text = re.sub(r"\s+", " ", container.inner_text(timeout=900)).strip()
    key = f"{selector}:{text[:240]}"
    if key not in seen:
     seen.add(key)
     yield container, text
   except (PlaywrightTimeout, PlaywrightError):
    continue

def _reliable_click(target, page) -> bool:
 try:
  target.scroll_into_view_if_needed(timeout=3000)
 except (AttributeError, PlaywrightError):
  pass
 try:
  target.click(timeout=4000)
 except PlaywrightError:
  try:
   target.click(timeout=4000, force=True)
  except PlaywrightError:
   try:
    box = target.bounding_box(timeout=1500)
    if not box:
     return False
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
   except (AttributeError, PlaywrightError):
    return False
 page.wait_for_timeout(250)
 return True

def _click_exact(container, pattern: re.Pattern[str], page) -> bool:
 button = container.get_by_role("button", name=pattern)
 if _visible(button, 350) and _reliable_click(button.first, page):
  return True
 text = container.get_by_text(pattern, exact=True)
 if _visible(text, 350):
  target = text.first
  try:
   ancestor = target.locator("xpath=ancestor::*[self::button or @role='button'][1]")
   if _visible(ancestor, 200):
    target = ancestor.first
  except PlaywrightError:
   pass
  if _reliable_click(target, page):
   return True
 candidates = container.locator(CLICKABLE_SELECTOR)
 try:
  count = min(candidates.count(), 50)
 except PlaywrightError:
  count = 0
 for index in range(count):
  candidate = candidates.nth(index)
  if pattern.fullmatch(_label(candidate)) and _visible(candidate, 200):
   if _reliable_click(candidate, page):
    return True
 return False

def _inside_content_check(candidate) -> bool:
 """Verify a global Aç candidate belongs to the content-check onboarding tree."""
 try:
  return bool(candidate.evaluate(
   """element => {
     let node = element;
     for (let depth = 0; node && depth < 12; depth++, node = node.parentElement) {
       const text = (node.innerText || '').replace(/\\s+/g, ' ').toLowerCase();
       if (text.includes('otomatik içerik kontrolleri') ||
           text.includes('müzik telif hakkı kontrolü') ||
           text.includes('içerik kontrolü (hafif)') ||
           text.includes('automatic content check') ||
           text.includes('copyright check')) return true;
     }
     return false;
   }"""
  ))
 except (AttributeError, PlaywrightError):
  return False

def _click_global_verified_enable(surface, page) -> bool:
 candidates = surface.locator(CLICKABLE_SELECTOR)
 try:
  count = min(candidates.count(), 120)
 except PlaywrightError:
  count = 0
 for index in range(count):
  candidate = candidates.nth(index)
  if not ENABLE_CONTENT_CHECK.fullmatch(_label(candidate)):
   continue
  if not _visible(candidate, 250) or not _inside_content_check(candidate):
   continue
  if _reliable_click(candidate, page):
   return True
 return False

def _surfaces(page):
 yield page
 try:
  for frame in page.frames:
   if frame is not page.main_frame:
    yield frame
 except (AttributeError, PlaywrightError):
  return

def _click_cookie(page, status=None) -> bool:
 for surface in _surfaces(page):
  for container, text in _containers(surface):
   if PUBLISH_TEXT.search(text):
    continue
   if _click_exact(container, COOKIE_ALLOW, page):
    _notify(status, "Çerez izni kabul edildi")
    return True
  global_button = surface.get_by_role("button", name=COOKIE_ALLOW)
  if _visible(global_button, 250) and _reliable_click(global_button.first, page):
   _notify(status, "Çerez izni kabul edildi")
   return True
 return False

def _enable_content_check(page, status=None) -> bool:
 for surface in _surfaces(page):
  for container, text in _containers(surface):
   if PUBLISH_TEXT.search(text) or not CONTENT_CHECK_TEXT.search(text):
    continue
   if _click_exact(container, ENABLE_CONTENT_CHECK, page):
    _notify(status, "Otomatik içerik kontrolleri Aç ile etkinleştirildi")
    return True
  if _click_global_verified_enable(surface, page):
   _notify(status, "Otomatik içerik kontrolleri Aç ile etkinleştirildi")
   return True
 return False

def _click_got_it(page, status=None) -> bool:
 for surface in _surfaces(page):
  for container, text in _containers(surface):
   if PUBLISH_TEXT.search(text):
    continue
   if _click_exact(container, GOT_IT, page):
    _notify(status, "TikTok bilgilendirmesi Anladım ile kapatıldı")
    return True
 return False

def clear_new_account_overlays(page, status: StatusCallback | None = None, timeout_seconds: float = 25.0, quiet_seconds: float = 2.0, minimum_scan_seconds: float = 4.0) -> int:
 """Clear cookie, click verified Aç, then close Anladım layers."""
 started = time.monotonic(); deadline = started + timeout_seconds; clicks = 0; quiet_since = started
 while time.monotonic() < deadline:
  if page.is_closed():
   return clicks
  clicked = _click_cookie(page, status) or _enable_content_check(page, status) or _click_got_it(page, status)
  if clicked:
   clicks += 1; quiet_since = time.monotonic(); continue
  now = time.monotonic()
  if now - started >= minimum_scan_seconds and now - quiet_since >= quiet_seconds:
   return clicks
  page.wait_for_timeout(150)
 return clicks
