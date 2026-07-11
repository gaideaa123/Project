from __future__ import annotations

"""Handle optional TikTok onboarding without disabling content checks."""

import re
import time
from collections.abc import Callable

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

StatusCallback = Callable[[str], None]
COOKIE_ALLOW = re.compile(
 r"^(tümüne izin ver|tüm çerezlere izin ver|çerezlere izin ver|"
 r"allow all|allow all cookies|accept all|accept all cookies)$", re.I,
)
CONTENT_CHECK_TEXT = re.compile(
 r"içerik kontrol|içeriği kontrol|telif hakkı kontrol|otomatik içerik kontrol|"
 r"sessize alınmasına neden olabilecek|content check|copyright check|muted",
 re.I,
)
ENABLE_CONTENT_CHECK = re.compile(
 r"^(aç|etkinleştir|kontrolü aç|içerik kontrolünü aç|"
 r"turn on|enable|enable check|turn on content check)$", re.I,
)
GOT_IT = re.compile(r"^(anladım|tamam|got it|understood|i understand)$", re.I)
PUBLISH_TEXT = re.compile(
 r"paylaşmaya devam|publish anyway|share now|post now|hemen paylaş|"
 r"hemen yayınla|yayınlamaya devam", re.I,
)
CONTAINER_SELECTORS = (
 '[role="dialog"]', '[aria-modal="true"]', '[role="alertdialog"]',
 '.TUXModal-overlay', '[data-floating-ui-portal]', '[class*="modal" i]',
 '[class*="dialog" i]', '[class*="banner" i]', '[class*="cookie" i]',
)


def _notify(status: StatusCallback | None, message: str) -> None:
 if status:
  status(message)


def _visible(locator, timeout: int = 250) -> bool:
 try:
  return bool(locator.count() and locator.first.is_visible(timeout=timeout))
 except (PlaywrightTimeout, PlaywrightError):
  return False


def _safe_click(locator) -> bool:
 try:
  locator.scroll_into_view_if_needed(timeout=1500)
 except (AttributeError, PlaywrightTimeout, PlaywrightError):
  pass
 try:
  locator.click(timeout=4000)
  return True
 except (PlaywrightTimeout, PlaywrightError):
  try:
   locator.click(timeout=4000, force=True)
   return True
  except (PlaywrightTimeout, PlaywrightError):
   return False


def _containers(page):
 seen: set[str] = set()
 for selector in CONTAINER_SELECTORS:
  locators = page.locator(selector)
  try:
   count = min(locators.count(), 30)
  except PlaywrightError:
   count = 0
  for index in range(count):
   container = locators.nth(index)
   try:
    if not container.is_visible(timeout=150):
     continue
    text = re.sub(r"\s+", " ", container.inner_text(timeout=700)).strip()
    key = f"{selector}:{text[:180]}"
    if key not in seen:
     seen.add(key)
     yield container, text
   except (PlaywrightTimeout, PlaywrightError):
    continue


def _click_exact(container, pattern: re.Pattern[str]) -> bool:
 button = container.get_by_role("button", name=pattern)
 if _visible(button, 300) and _safe_click(button.first):
  return True
 text = container.get_by_text(pattern, exact=True)
 if _visible(text, 300):
  target = text.first
  if _safe_click(target):
   return True
  try:
   parent = target.locator("xpath=ancestor::*[self::button or @role='button'][1]")
   if _safe_click(parent):
    return True
  except PlaywrightError:
   pass
 candidates = container.locator("button, [role='button']")
 try:
  count = min(candidates.count(), 30)
 except PlaywrightError:
  count = 0
 for index in range(count):
  candidate = candidates.nth(index)
  try:
   label = re.sub(
    r"\s+", " ", candidate.get_attribute("aria-label")
    or candidate.inner_text(timeout=400) or "",
   ).strip()
   if pattern.fullmatch(label) and candidate.is_visible(timeout=200) and _safe_click(candidate):
    return True
  except (PlaywrightTimeout, PlaywrightError):
   continue
 return False


def _candidate_belongs_to_content_check(candidate) -> bool:
 """Verify a global Aç candidate belongs to a content-check modal/portal."""
 try:
  return bool(candidate.evaluate("""el => {
   const root = el.closest('[role="dialog"], [role="alertdialog"], [aria-modal="true"], .TUXModal-overlay, [data-floating-ui-portal]');
   if (!root) return false;
   const text = (root.innerText || root.textContent || '').toLowerCase();
   return /içerik kontrol|içeriği kontrol|telif hakkı kontrol|sessize alınmasına neden olabilecek|content check|copyright check|muted/.test(text)
     && !/hemen paylaş|paylaşmaya devam|publish anyway|share now|post now/.test(text);
  }"""))
 except (AttributeError, PlaywrightError):
  return False


def _click_global_verified_enable(page, scope=None) -> bool:
 """Fallback for TikTok floating portals that sit outside normal modal trees."""
 root = scope or page
 try:
  candidates = root.locator("button, [role='button']")
  count = min(candidates.count(), 80)
 except (AttributeError, PlaywrightError):
  return False
 for index in range(count):
  candidate = candidates.nth(index)
  try:
   label = re.sub(
    r"\s+", " ", candidate.get_attribute("aria-label")
    or candidate.inner_text(timeout=400) or "",
   ).strip()
   if not ENABLE_CONTENT_CHECK.fullmatch(label):
    continue
   if not candidate.is_visible(timeout=200) or not _candidate_belongs_to_content_check(candidate):
    continue
   if _safe_click(candidate):
    return True
  except (PlaywrightTimeout, PlaywrightError):
   continue
 return False


def _click_cookie(page, status=None) -> bool:
 for container, text in _containers(page):
  if PUBLISH_TEXT.search(text):
   continue
  if _click_exact(container, COOKIE_ALLOW):
   _notify(status, "Çerez izni kabul edildi")
   page.wait_for_timeout(300)
   return True
 global_button = page.get_by_role("button", name=COOKIE_ALLOW)
 if _visible(global_button, 250) and _safe_click(global_button.first):
  _notify(status, "Çerez izni kabul edildi")
  page.wait_for_timeout(300)
  return True
 return False


def _enable_content_check(page, status=None) -> bool:
 """Click Aç only inside a verified content-check onboarding container."""
 for container, text in _containers(page):
  if PUBLISH_TEXT.search(text) or not CONTENT_CHECK_TEXT.search(text):
   continue
  if _click_exact(container, ENABLE_CONTENT_CHECK):
   _notify(status, "İçerik kontrolü Aç ile etkinleştirildi")
   page.wait_for_timeout(400)
   return True
 if _click_global_verified_enable(page, page):
  _notify(status, "İçerik kontrolü Aç ile etkinleştirildi")
  page.wait_for_timeout(400)
  return True
 return False


def _click_got_it(page, status=None) -> bool:
 for container, text in _containers(page):
  if PUBLISH_TEXT.search(text):
   continue
  if _click_exact(container, GOT_IT):
   _notify(status, "TikTok bilgilendirmesi Anladım ile kapatıldı")
   page.wait_for_timeout(300)
   return True
 return False


def clear_new_account_overlays(
 page,
 status: StatusCallback | None = None,
 timeout_seconds: float = 20.0,
 quiet_seconds: float = 1.5,
) -> int:
 """Clear cookie -> content check Aç -> every Anladım, including floating portals."""
 deadline = time.monotonic() + timeout_seconds
 clicks = 0
 quiet_since = time.monotonic()
 while time.monotonic() < deadline:
  if page.is_closed():
   return clicks
  clicked = _click_cookie(page, status) or _enable_content_check(page, status) or _click_got_it(page, status)
  if clicked:
   clicks += 1
   quiet_since = time.monotonic()
   continue
  if time.monotonic() - quiet_since >= quiet_seconds:
   return clicks
  page.wait_for_timeout(150)
 return clicks
