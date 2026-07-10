from __future__ import annotations

"""Visible TikTok Studio uploader. Login, CAPTCHA, 2FA and final approval stay with the user."""

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


class UploadError(RuntimeError):
    pass


@dataclass(frozen=True)
class UploadRequest:
    profile: str
    video: Path
    caption: str

    def validate(self) -> None:
        if not self.profile.strip():
            raise UploadError("Profil adı boş")
        if not self.video.is_file() or self.video.suffix.lower() not in MEDIA_EXTENSIONS:
            raise UploadError(f"Geçerli video bulunamadı: {self.video}")
        if self.video.stat().st_size <= 0:
            raise UploadError(f"Video boş: {self.video}")
        if not self.caption.strip():
            raise UploadError("Caption boş")
        if len(self.caption) > 2200:
            raise UploadError("Caption 2200 karakterden uzun")


def safe_profile_name(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-.")
    if not clean:
        raise UploadError("Profil adı dosya sistemi için geçersiz")
    return clean[:80]


def first_visible(locators: Iterable[Locator], timeout_ms: int = 1200) -> Locator | None:
    for locator in locators:
        try:
            if locator.first.is_visible(timeout=timeout_ms):
                return locator.first
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return None


def publish_candidates(page: Page) -> list[Locator]:
    return [
        page.get_by_role("button", name=re.compile(r"^post$|^publish$|^yayınla$|^paylaş$", re.I)),
        page.locator('button[data-e2e*="post" i]'),
        page.locator('button[data-e2e*="publish" i]'),
    ]


def wait_for_login(page: Page, timeout_seconds: int = 600) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            field = page.locator('input[type="file"]')
            if "/login" not in page.url.lower() and field.count() and field.first.is_attached():
                return
        except PlaywrightError:
            pass
        page.wait_for_timeout(1000)
    raise UploadError("Giriş için 10 dakika doldu. Tarayıcıdan giriş yapıp yeniden deneyin")


def upload_file(page: Page, video: Path) -> None:
    direct = page.locator('input[type="file"]')
    try:
        if direct.count():
            direct.first.set_input_files(str(video.resolve()))
            return
    except PlaywrightError:
        pass
    trigger = first_visible([
        page.get_by_role("button", name=re.compile(r"select|upload|choose|yükle|seç", re.I)),
        page.get_by_text(re.compile(r"select video|upload video|video seç|video yükle", re.I)),
    ], 2500)
    if trigger is None:
        raise UploadError("Video seçim alanı bulunamadı. TikTok Studio arayüzü değişmiş olabilir")
    try:
        with page.expect_file_chooser(timeout=5000) as chooser_info:
            trigger.click()
        chooser_info.value.set_files(str(video.resolve()))
    except PlaywrightTimeout as exc:
        raise UploadError("TikTok dosya seçiciyi açmadı") from exc


def caption_candidates(page: Page) -> list[Locator]:
    return [
        page.locator('[contenteditable="true"][data-e2e*="caption" i]'),
        page.locator('[contenteditable="true"][aria-label*="caption" i]'),
        page.locator('[contenteditable="true"][aria-label*="description" i]'),
        page.get_by_role("textbox", name=re.compile(r"caption|description|açıklama", re.I)),
        page.locator('textarea[placeholder*="caption" i]'),
        page.locator('textarea[placeholder*="description" i]'),
    ]


def fill_caption(page: Page, caption: str, timeout_seconds: int = 180) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        field = first_visible(caption_candidates(page), 800)
        if field is not None:
            field.click()
            tag = field.evaluate("el => el.tagName.toLowerCase()")
            if tag in {"textarea", "input"}:
                field.fill(caption)
            else:
                field.press("ControlOrMeta+A")
                field.press("Backspace")
                field.type(caption, delay=1)
            return
        page.wait_for_timeout(1000)
    raise UploadError("Caption alanı yüklenmedi. Video işleme tamamlanmamış olabilir")


def wait_until_ready(page: Page, timeout_seconds: int = 600) -> Locator:
    deadline = time.monotonic() + timeout_seconds
    failure = re.compile(r"upload failed|couldn't upload|yükleme başarısız|unsupported", re.I)
    while time.monotonic() < deadline:
        try:
            if failure.search(page.locator("body").inner_text(timeout=2000)):
                raise UploadError("TikTok videoyu reddetti: sayfadaki hata mesajını kontrol edin")
        except PlaywrightTimeout:
            pass
        publish = first_visible(publish_candidates(page), 500)
        if publish is not None:
            try:
                if publish.is_enabled():
                    return publish
            except PlaywrightError:
                pass
        page.wait_for_timeout(1500)
    raise UploadError("TikTok video işlemeyi 10 dakikada tamamlamadı")


def save_diagnostics(page: Page, profile: str, error: Exception) -> Path:
    folder = DATA_ROOT / "diagnostics" / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    folder.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(folder / "page.png"), full_page=True)
    except PlaywrightError:
        pass
    try:
        (folder / "page.html").write_text(page.content(), encoding="utf-8")
    except PlaywrightError:
        pass
    (folder / "error.json").write_text(json.dumps({
        "profile": profile, "url": page.url, "error_type": type(error).__name__,
        "error": str(error), "time": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


def launch_context(playwright: Playwright, profile: str) -> BrowserContext:
    profile_dir = DATA_ROOT / "profiles" / safe_profile_name(profile)
    profile_dir.mkdir(parents=True, exist_ok=True)
    options = dict(user_data_dir=str(profile_dir), headless=False, viewport=None,
                   no_viewport=True, args=["--start-maximized"])
    try:
        return playwright.chromium.launch_persistent_context(channel="chrome", **options)
    except PlaywrightError as chrome_error:
        try:
            return playwright.chromium.launch_persistent_context(**options)
        except PlaywrightError as bundled_error:
            raise UploadError(
                "Chrome ve Playwright Chromium açılamadı. `playwright install chromium` çalıştırın. "
                f"Chrome: {chrome_error}; Chromium: {bundled_error}"
            ) from bundled_error


def wait_for_publish_result(page: Page, timeout_seconds: int = 120) -> None:
    deadline = time.monotonic() + timeout_seconds
    success = re.compile(r"posted|published|upload complete|yayınlandı|paylaşıldı", re.I)
    failure = re.compile(r"failed|error|try again|başarısız|hata|tekrar dene", re.I)
    while time.monotonic() < deadline:
        try:
            text = page.locator("body").inner_text(timeout=2000)
            if success.search(text) or "upload" not in page.url.lower():
                return
            if failure.search(text):
                raise UploadError("TikTok yayını reddetti. Tarayıcıdaki hata mesajını kontrol edin")
        except PlaywrightTimeout:
            pass
        page.wait_for_timeout(1000)
    raise UploadError("Yayın sonucu iki dakika içinde doğrulanamadı")


def prepare_upload(
    request: UploadRequest,
    publish: bool = False,
    approval: Callable[[], bool] | None = None,
) -> None:
    request.validate()
    with sync_playwright() as playwright:
        context = launch_context(playwright, request.profile)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            wait_for_login(page)
            upload_file(page, request.video)
            fill_caption(page, request.caption.strip())
            button = wait_until_ready(page)
            page.bring_to_front()
            if publish:
                approved = approval() if approval else (
                    input(f"Önizlemeyi kontrol edin. Yayınlamak için {CONFIRMATION} yazın: ").strip()
                    == CONFIRMATION
                )
                if not approved:
                    raise UploadError("Yayın kullanıcı tarafından iptal edildi")
                button.click()
                wait_for_publish_result(page)
            else:
                print("HAZIR: Video ve caption dolduruldu. Son yayın işlemi tarayıcıda sizde.")
                while context.pages:
                    page.wait_for_timeout(1000)
        except Exception as exc:
            folder = save_diagnostics(page, request.profile, exc)
            raise UploadError(f"{exc}\nTanı dosyaları: {folder}") from exc
        finally:
            context.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="TikTok Studio görünür web yükleme yardımcısı")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--video", required=True, type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--caption")
    group.add_argument("--caption-file", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    try:
        caption = args.caption if args.caption is not None else args.caption_file.read_text(encoding="utf-8-sig")
        prepare_upload(UploadRequest(args.profile, args.video.expanduser().resolve(), caption), args.publish)
        return 0
    except (OSError, UnicodeError, UploadError) as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
