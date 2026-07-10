from __future__ import annotations

"""Visible TikTok Studio uploader with persistent, user-controlled login."""

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from platformdirs import user_data_dir
from playwright.sync_api import (
    BrowserContext, Error as PlaywrightError, Locator, Page, Playwright,
    TimeoutError as PlaywrightTimeout, sync_playwright,
)

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=creator_center"
DATA_ROOT = Path(user_data_dir("signaldesk-web-uploader", "SignalDesk"))
MEDIA_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}
CONFIRMATION = "ONAYLA VE YAYINLA"
StatusCallback = Callable[[str], None]

class UploadError(RuntimeError): pass

@dataclass(frozen=True)
class UploadRequest:
    profile: str
    video: Path
    caption: str
    def validate(self) -> None:
        if not self.profile.strip(): raise UploadError("Profil adı boş")
        if not self.video.is_file() or self.video.suffix.lower() not in MEDIA_EXTENSIONS:
            raise UploadError(f"Geçerli video bulunamadı: {self.video}")
        if self.video.stat().st_size <= 0: raise UploadError(f"Video boş: {self.video}")
        if not self.caption.strip(): raise UploadError("Caption boş")
        if len(self.caption) > 2200: raise UploadError("Caption 2200 karakterden uzun")

def safe_profile_name(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-.")
    if not clean: raise UploadError("Profil adı dosya sistemi için geçersiz")
    return clean[:80]

def notify(callback, message):
    print(message)
    if callback: callback(message)

def first_visible(locators: Iterable[Locator], timeout_ms=1200):
    for locator in locators:
        try:
            if locator.first.is_visible(timeout=timeout_ms): return locator.first
        except (PlaywrightTimeout, PlaywrightError): pass
    return None

def file_input_ready(page: Page) -> bool:
    try: return page.locator('input[type="file"]').count() > 0
    except PlaywrightError: return False

def login_ui_visible(page: Page) -> bool:
    try:
        password = page.locator('input[type="password"]')
        if password.count() and password.first.is_visible(timeout=250): return True
        text = page.get_by_text(re.compile(r"log in|sign in|giriş yap|telefon.*e-posta", re.I))
        return bool(text.count() and text.first.is_visible(timeout=250))
    except (PlaywrightTimeout, PlaywrightError): return False

def wait_for_upload_after_login(page, timeout_seconds=900, status=None):
    deadline = time.monotonic() + timeout_seconds; login_seen = False; last_nav = 0.0
    while time.monotonic() < deadline:
        if page.is_closed(): raise UploadError("TikTok penceresi kapatıldı")
        if file_input_ready(page): notify(status, "TikTok oturumu hazır; upload ekranı açıldı"); return
        now = time.monotonic(); url = page.url.lower()
        if login_ui_visible(page) or "/login" in url:
            login_seen = True; page.bring_to_front(); page.wait_for_timeout(750); continue
        if (login_seen or "tiktokstudio/upload" not in url) and now - last_nav > 4:
            try: page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            except PlaywrightTimeout: pass
            last_nav = now; continue
        page.wait_for_timeout(750)
    raise UploadError("TikTok girişi veya upload ekranı 15 dakikada tamamlanmadı")

def upload_file(page: Page, video: Path) -> None:
    direct = page.locator('input[type="file"]')
    try:
        if direct.count(): direct.first.set_input_files(str(video.resolve())); return
    except PlaywrightError: pass
    trigger = first_visible([
        page.get_by_role("button", name=re.compile(r"select|upload|choose|yükle|seç", re.I)),
        page.get_by_text(re.compile(r"select video|upload video|video seç|video yükle", re.I)),
    ], 2500)
    if trigger is None: raise UploadError("Video seçim alanı bulunamadı")
    try:
        with page.expect_file_chooser(timeout=5000) as info: trigger.click()
        info.value.set_files(str(video.resolve()))
    except PlaywrightTimeout as exc: raise UploadError("TikTok dosya seçiciyi açmadı") from exc

def caption_candidates(page: Page) -> list[Locator]:
    return [
        page.locator('[data-e2e="caption-container"] [contenteditable="true"]'),
        page.locator('[data-e2e*="caption" i] [contenteditable="true"]'),
        page.locator('[class*="caption" i] [contenteditable="true"]'),
        page.locator('[contenteditable="true"][aria-label*="caption" i]'),
        page.locator('[contenteditable="true"][aria-label*="description" i]'),
        page.locator('[contenteditable="true"][role="textbox"]'),
        page.get_by_role("textbox", name=re.compile(r"caption|description|açıklama|video description", re.I)),
        page.locator('textarea[placeholder*="caption" i]'),
        page.locator('textarea[placeholder*="description" i]'),
    ]

def _caption_value(field: Locator) -> str:
    try:
        tag = field.evaluate("el => el.tagName.toLowerCase()")
        if tag in {"input", "textarea"}: return field.input_value(timeout=1000).strip()
        return field.inner_text(timeout=1000).strip()
    except PlaywrightError: return ""

def _write_caption(field: Locator, caption: str) -> None:
    field.scroll_into_view_if_needed(timeout=3000)
    field.click(timeout=3000)
    tag = field.evaluate("el => el.tagName.toLowerCase()")
    if tag in {"input", "textarea"}:
        field.fill(caption, timeout=5000)
    else:
        # fill() supports [contenteditable] and correctly emits input events.
        try: field.fill(caption, timeout=5000)
        except PlaywrightError:
            field.press("ControlOrMeta+A"); field.press("Backspace"); field.type(caption, delay=2)
    field.evaluate("el => { el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText'})); el.dispatchEvent(new Event('change', {bubbles:true})); }")

def fill_caption(page: Page, caption: str, timeout_seconds=180) -> None:
    expected = re.sub(r"\s+", " ", caption).strip()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for candidate in caption_candidates(page):
            field = first_visible([candidate], 500)
            if field is None: continue
            try:
                _write_caption(field, caption)
                actual = re.sub(r"\s+", " ", _caption_value(field)).strip()
                if actual == expected or expected in actual:
                    return
            except PlaywrightError:
                continue
        page.wait_for_timeout(1000)
    raise UploadError("Caption alanı bulundu ama metin doğrulanamadı; TikTok editörü değişmiş olabilir")

def publish_candidates(page):
    return [page.get_by_role("button", name=re.compile(r"^post$|^publish$|^yayınla$|^paylaş$", re.I)), page.locator('button[data-e2e*="post" i]'), page.locator('button[data-e2e*="publish" i]')]

def wait_until_ready(page, timeout_seconds=600):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        button = first_visible(publish_candidates(page), 500)
        if button is not None:
            try:
                if button.is_enabled(): return button
            except PlaywrightError: pass
        page.wait_for_timeout(1500)
    raise UploadError("TikTok video işlemeyi 10 dakikada tamamlamadı")

def wait_for_publish_result(page, timeout_seconds=120):
    deadline = time.monotonic() + timeout_seconds
    success = re.compile(r"posted|published|upload complete|yayınlandı|paylaşıldı", re.I)
    while time.monotonic() < deadline:
        try:
            if success.search(page.locator("body").inner_text(timeout=2000)) or "upload" not in page.url.lower(): return
        except PlaywrightError: pass
        page.wait_for_timeout(1000)
    raise UploadError("Yayın sonucu iki dakika içinde doğrulanamadı")

def save_diagnostics(page, profile, error):
    folder = DATA_ROOT / "diagnostics" / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    folder.mkdir(parents=True, exist_ok=True)
    try: page.screenshot(path=str(folder / "page.png"), full_page=True); (folder / "page.html").write_text(page.content(), encoding="utf-8")
    except PlaywrightError: pass
    (folder / "error.json").write_text(json.dumps({"profile":profile,"url":page.url,"error_type":type(error).__name__,"error":str(error),"time":datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder

def launch_context(playwright: Playwright, profile: str):
    folder = DATA_ROOT / "profiles" / safe_profile_name(profile); folder.mkdir(parents=True, exist_ok=True)
    options = dict(user_data_dir=str(folder), headless=False, viewport=None, no_viewport=True, args=["--start-maximized"])
    try: return playwright.chromium.launch_persistent_context(channel="chrome", **options)
    except PlaywrightError:
        try: return playwright.chromium.launch_persistent_context(**options)
        except PlaywrightError as exc: raise UploadError("Chrome açılamadı; `playwright install chromium` çalıştırın") from exc

def prepare_upload(request, publish=False, approval=None, status=None):
    request.validate()
    with sync_playwright() as playwright:
        context = launch_context(playwright, request.profile); page = context.pages[0] if context.pages else context.new_page()
        try:
            notify(status, "TikTok Studio açılıyor"); page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            wait_for_upload_after_login(page, status=status); notify(status, "Video yükleniyor")
            upload_file(page, request.video); fill_caption(page, request.caption.strip()); notify(status, "Caption yazıldı ve doğrulandı")
            button = wait_until_ready(page); page.bring_to_front()
            if publish:
                approved = approval() if approval else input(f"Yayınlamak için {CONFIRMATION} yazın: ").strip() == CONFIRMATION
                if not approved: raise UploadError("Yayın kullanıcı tarafından iptal edildi")
                button.click(); wait_for_publish_result(page)
            else:
                while context.pages: page.wait_for_timeout(1000)
        except Exception as exc:
            folder = save_diagnostics(page, request.profile, exc); raise UploadError(f"{exc}\nTanı dosyaları: {folder}") from exc
        finally: context.close()

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--profile", required=True); parser.add_argument("--video", required=True, type=Path)
    group = parser.add_mutually_exclusive_group(required=True); group.add_argument("--caption"); group.add_argument("--caption-file", type=Path)
    parser.add_argument("--publish", action="store_true"); args = parser.parse_args()
    try:
        caption = args.caption if args.caption is not None else args.caption_file.read_text(encoding="utf-8-sig")
        prepare_upload(UploadRequest(args.profile, args.video.expanduser().resolve(), caption), args.publish); return 0
    except Exception as exc: print(f"HATA: {exc}", file=sys.stderr); return 1

if __name__ == "__main__": raise SystemExit(main())
