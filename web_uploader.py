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


def notify(callback: StatusCallback | None, message: str) -> None:
    print(message)
    if callback:
        callback(message)


def first_visible(locators: Iterable[Locator], timeout_ms: int = 1200) -> Locator | None:
    for locator in locators:
        try:
            if locator.first.is_visible(timeout=timeout_ms):
                return locator.first
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return None


def file_input_ready(page: Page) -> bool:
    try:
        field = page.locator('input[type="file"]')
        return bool(field.count() and field.first.is_attached())
    except PlaywrightError:
        return False


def login_ui_visible(page: Page) -> bool:
    """Detect both full-page and modal login without relying only on the URL."""
    try:
        password = page.locator('input[type="password"]')
        if password.count() and password.first.is_visible(timeout=250):
            return True
        login_text = page.get_by_text(re.compile(r"log in|sign in|giriş yap|telefon.*e-posta", re.I))
        return bool(login_text.count() and login_text.first.is_visible(timeout=250))
    except (PlaywrightTimeout, PlaywrightError):
        return False


def wait_for_upload_after_login(
    page: Page,
    timeout_seconds: int = 900,
    status: StatusCallback | None = None,
) -> None:
    """Wait for manual login, then force navigation back from TikTok home to Studio upload."""
    deadline = time.monotonic() + timeout_seconds
    login_seen = False
    last_navigation = 0.0
    last_notice = 0.0

    while time.monotonic() < deadline:
        if page.is_closed():
            raise UploadError("TikTok penceresi kapatıldı")
        if file_input_ready(page):
            notify(status, "TikTok oturumu hazır; video yükleme ekranı açıldı")
            return

        now = time.monotonic()
        url = page.url.lower()
        login_visible = login_ui_visible(page) or "/login" in url
        if login_visible:
            login_seen = True
            if now - last_notice > 12:
                notify(status, "TikTok penceresinde giriş, CAPTCHA veya 2FA adımını tamamlayın")
                last_notice = now
            page.bring_to_front()
            page.wait_for_timeout(750)
            continue

        # TikTok successful login usually redirects to For You/Home instead of back
        # to Studio. The old code waited forever there. Return to upload explicitly.
        on_upload_route = "tiktokstudio/upload" in url
        if (login_seen or not on_upload_route) and now - last_navigation > 4:
            notify(status, "Giriş algılandı; TikTok Studio yükleme ekranına dönülüyor")
            try:
                page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            except PlaywrightTimeout:
                pass
            last_navigation = now
            page.wait_for_timeout(750)
            continue

        page.wait_for_timeout(750)

    raise UploadError("TikTok girişi veya yükleme ekranı 15 dakika içinde tamamlanmadı")


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


def publish_candidates(page: Page) -> list[Locator]:
    return [
        page.get_by_role("button", name=re.compile(r"^post$|^publish$|^yayınla$|^paylaş$", re.I)),
        page.locator('button[data-e2e*="post" i]'),
        page.locator('button[data-e2e*="publish" i]'),
    ]


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


def save_diagnostics(page: Page, profile: str, error: Exception) -> Path:
    folder = DATA_ROOT / "diagnostics" / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    folder.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(folder / "page.png"), full_page=True)
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


def prepare_upload(
    request: UploadRequest,
    publish: bool = False,
    approval: Callable[[], bool] | None = None,
    status: StatusCallback | None = None,
) -> None:
    request.validate()
    with sync_playwright() as playwright:
        context = launch_context(playwright, request.profile)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            notify(status, "TikTok Studio açılıyor")
            page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            wait_for_upload_after_login(page, status=status)
            notify(status, "Video yükleniyor")
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
                notify(status, "Hazır: son yayın işlemi tarayıcıda sizde")
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
