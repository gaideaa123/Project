from __future__ import annotations

"""Automatic publish flow that waits for finished checks and handles advisory warnings."""

import inspect
import re
import time
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout, sync_playwright

import publication_guard

Status = Callable[[str], None]
PUBLISH_BUTTON = re.compile(r"^(paylaş|yayınla|gönder|post|publish|share)$", re.I)
CONTINUE_BUTTON = re.compile(
 r"^(yine de paylaş|paylaşmaya devam|yine de yayınla|yayınlamaya devam|"
 r"share anyway|post anyway|publish anyway|continue sharing|continue publishing)$",
 re.I,
)
CHECK_PENDING = re.compile(
 r"(?:içerik|telif|müzik).{0,35}(?:kontrol ediliyor|inceleniyor|sürüyor|bekleniyor|tamamlanmadı)|"
 r"(?:content|copyright|music).{0,35}(?:checking|in progress|processing|pending|not finished)",
 re.I,
)
UPLOAD_PENDING = re.compile(
 r"(?:video\s*)?(?:yükleniyor|işleniyor|hazırlanıyor)\s*\d{0,3}\s*%?|"
 r"(?:uploading|processing)\s*(?:video)?\s*\d{0,3}\s*%?",
 re.I,
)
ADVISORY = re.compile(
 r"özgün olmayan, düşük kaliteli ve qr kodlu içerik|"
 r"özgün olmayan ve düşük kaliteli içerik|"
 r"unoriginal, low-quality|qr code content|not eligible for recommendation",
 re.I,
)
HARD_FAILURE = re.compile(
 r"yükleme başarısız|video yüklenemedi|paylaşım başarısız|gönderilemedi|"
 r"upload failed|failed to upload|publish failed|couldn.t post",
 re.I,
)
DIALOGS = ('[role="dialog"]', '[aria-modal="true"]', '[class*="modal" i]', '[class*="dialog" i]', '[class*="popup" i]')

def _status(callback: Status | None, message: str) -> None:
 if callback:
  callback(message)

def _body(page) -> str:
 try:
  return page.locator("body").inner_text(timeout=1800)
 except (PlaywrightTimeout, PlaywrightError):
  return ""

def _first_publish(page):
 candidates = [
  page.get_by_role("button", name=PUBLISH_BUTTON),
  page.locator('button[data-e2e*="post" i]'),
  page.locator('button[data-e2e*="publish" i]'),
 ]
 for locator in candidates:
  try:
   item = locator.first
   if item.is_visible(timeout=350):
    return item
  except (PlaywrightTimeout, PlaywrightError):
   continue
 return None

def _progress_busy(page) -> bool:
 bars = page.locator('[role="progressbar"]')
 try:
  count = min(bars.count(), 12)
 except PlaywrightError:
  return True
 for index in range(count):
  bar = bars.nth(index)
  try:
   if not bar.is_visible(timeout=100):
    continue
   value = bar.get_attribute("aria-valuenow")
   if value is None or float(value) < 100:
    return True
  except (PlaywrightError, ValueError):
   return True
 return False

def wait_for_checks_complete(page, status: Status | None = None, timeout_seconds: int = 900):
 """Return a stable enabled Publish button only after upload/check activity ends."""
 deadline = time.monotonic() + timeout_seconds
 stable = 0
 last_notice = 0.0
 while time.monotonic() < deadline:
  if page.is_closed():
   raise RuntimeError("TikTok penceresi içerik kontrolü tamamlanmadan kapatıldı")
  text = _body(page)
  failed = HARD_FAILURE.search(text)
  if failed:
   raise RuntimeError(f"TikTok yükleme hatası gösteriyor: {failed.group(0)}")
  pending = bool(CHECK_PENDING.search(text) or UPLOAD_PENDING.search(text) or _progress_busy(page))
  button = _first_publish(page)
  enabled = False
  if button is not None:
   try:
    enabled = button.is_enabled()
   except PlaywrightError:
    enabled = False
  if enabled and not pending:
   stable += 1
   if stable >= 3:
    _status(status, "Video yüklendi, içerik kontrolleri tamamlandı; Paylaş hazır")
    return button
  else:
   stable = 0
  now = time.monotonic()
  if now - last_notice >= 8:
   _status(status, "Video yükleme ve içerik kontrolünün tamamlanması bekleniyor")
   last_notice = now
  page.wait_for_timeout(1000)
 raise RuntimeError("TikTok içerik kontrolünü 15 dakikada tamamlamadı")

def _click(locator, page) -> bool:
 try:
  locator.scroll_into_view_if_needed(timeout=2500)
 except (AttributeError, PlaywrightError):
  pass
 try:
  locator.click(timeout=5000)
  return True
 except PlaywrightError:
  try:
   locator.click(timeout=5000, force=True)
   return True
  except PlaywrightError:
   try:
    box = locator.bounding_box(timeout=1500)
    if not box:
     return False
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    return True
   except (AttributeError, PlaywrightError):
    return False

def handle_advisory_dialog(page, status: Status | None = None, timeout_seconds: int = 12) -> bool:
 """Continue only through the explicit non-blocking quality advisory dialog."""
 deadline = time.monotonic() + timeout_seconds
 while time.monotonic() < deadline:
  for selector in DIALOGS:
   dialogs = page.locator(selector)
   try:
    count = min(dialogs.count(), 20)
   except PlaywrightError:
    count = 0
   for index in range(count):
    dialog = dialogs.nth(index)
    try:
     if not dialog.is_visible(timeout=150):
      continue
     text = dialog.inner_text(timeout=800)
     if not ADVISORY.search(text):
      continue
     button = dialog.get_by_role("button", name=CONTINUE_BUTTON).first
     if button.is_visible(timeout=300) and _click(button, page):
      _status(status, "TikTok özgünlük/kalite uyarısı kaydedildi; 'Yine de paylaş' seçildi")
      page.wait_for_timeout(500)
      return True
    except (PlaywrightTimeout, PlaywrightError):
     continue
  page.wait_for_timeout(250)
 return False

def _supported(function, values: dict[str, Any]) -> dict[str, Any]:
 parameters = inspect.signature(function).parameters.values()
 if any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters):
  return values
 names = {item.name for item in parameters}
 return {key: value for key, value in values.items() if key in names}

def install(web_uploader: Any) -> None:
 if getattr(web_uploader, "_automatic_publish_installed", False):
  return
 required = ("launch_context", "wait_for_login", "upload_file", "fill_caption", "goto_upload")
 if not all(callable(getattr(web_uploader, name, None)) for name in required):
  raise RuntimeError("Web uploader otomatik yayın için gerekli metotları sunmuyor")
 request_type = web_uploader.UploadRequest

 def prepare_upload(request, publish: bool = False, approval=None, status: Status | None = None):
  request.validate()
  with sync_playwright() as playwright:
   context = web_uploader.launch_context(playwright, request.profile)
   page = context.pages[0] if context.pages else context.new_page()
   try:
    _status(status, f"{request.profile}: TikTok Studio açılıyor")
    web_uploader.goto_upload(page)
    web_uploader.wait_for_login(page)
    web_uploader.upload_file(page, request.video)
    web_uploader.fill_caption(page, request.caption)
    button = wait_for_checks_complete(page, status=status)
    page.bring_to_front()
    if not publish:
     _status(status, "Hazır; Paylaş düğmesi kullanıcıya bırakıldı")
     while context.pages:
      page.wait_for_timeout(1000)
     return
    publication_guard.assert_publishable(page, status)
    _status(status, f"{request.profile}: içerik kontrolü bitti, Paylaş tıklanıyor")
    if not _click(button, page):
     raise RuntimeError("TikTok Paylaş düğmesine tıklanamadı")
    handle_advisory_dialog(page, status=status)
    publication_guard.wait_for_verified_publication(page, request.profile, status=status, timeout_seconds=180)
   except Exception as exc:
    folder = web_uploader.save_diagnostics(page, request.profile, exc)
    raise web_uploader.UploadError(f"{exc}\nTanı dosyaları: {folder}") from exc
   finally:
    context.close()

 web_uploader.prepare_upload = prepare_upload
 web_uploader.UploadRequest = request_type
 web_uploader._automatic_publish_installed = True
