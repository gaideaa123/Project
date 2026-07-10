from __future__ import annotations

"""Visible TikTok Studio uploader with ordered, profile-scoped publishing."""

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
NOTICE_BUTTON = re.compile(r"^(anladım|tamam|got it|i understand|understood)$", re.I)
PUBLISH_BUTTON = re.compile(r"^(post|publish|share|yayınla|paylaş)$", re.I)
PUBLISH_CONFIRM = re.compile(r"^(post now|publish now|share now|şimdi yayınla|şimdi paylaş)$", re.I)
UPLOAD_FAILURE = re.compile(
    r"upload failed|couldn't upload|failed to upload|yükleme başarısız|video yüklenemedi|unsupported",
    re.I,
)
UPLOAD_BUSY_TEXT = re.compile(
    r"(?:uploading|processing|yükleniyor|işleniyor)\s*(?:video)?\s*\d{1,3}\s*%",
    re.I,
)
PUBLISH_SUCCESS = re.compile(
    r"posted|published|shared|upload complete|yayınlandı|paylaşıldı|gönderildi",
    re.I,
)


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
        return page.locator('input[type="file"]').count() > 0
    except PlaywrightError:
        return False


def login_ui_visible(page: Page) -> bool:
    try:
        password = page.locator('input[type="password"]')
        if password.count() and password.first.is_visible(timeout=250):
            return True
        text = page.get_by_text(re.compile(r"log in|sign in|giriş yap|telefon.*e-posta", re.I))
        return bool(text.count() and text.first.is_visible(timeout=250))
    except (PlaywrightTimeout, PlaywrightError):
        return False


def wait_for_upload_after_login(page: Page, timeout_seconds: int = 900, status=None) -> None:
    deadline = time.monotonic() + timeout_seconds
    login_seen = False
    last_navigation = 0.0
    while time.monotonic() < deadline:
        if page.is_closed():
            raise UploadError("TikTok penceresi kapatıldı")
        if file_input_ready(page):
            notify(status, "TikTok oturumu hazır; upload ekranı açıldı")
            return
        now = time.monotonic()
        url = page.url.lower()
        if login_ui_visible(page) or "/login" in url:
            login_seen = True
            page.bring_to_front()
            page.wait_for_timeout(750)
            continue
        if (login_seen or "tiktokstudio/upload" not in url) and now - last_navigation > 4:
            try:
                page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            except PlaywrightTimeout:
                pass
            last_navigation = now
            continue
        page.wait_for_timeout(750)
    raise UploadError("TikTok girişi veya upload ekranı 15 dakikada tamamlanmadı")


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
        raise UploadError("Video seçim alanı bulunamadı")
    try:
        with page.expect_file_chooser(timeout=5000) as info:
            trigger.click()
        info.value.set_files(str(video.resolve()))
    except PlaywrightTimeout as exc:
        raise UploadError("TikTok dosya seçiciyi açmadı") from exc


def dismiss_pre_caption_notice(
    page: Page,
    status: StatusCallback | None = None,
    timeout_seconds: int = 45,
    optional_after_seconds: int = 8,
) -> bool:
    """Dismiss TikTok's post-upload Anladım/Got it modal before editing caption."""
    deadline = time.monotonic() + timeout_seconds
    optional_deadline = time.monotonic() + optional_after_seconds
    while time.monotonic() < deadline:
        if page.is_closed():
            raise UploadError("TikTok penceresi kapatıldı")
        candidates = [
            page.get_by_role("dialog").get_by_role("button", name=NOTICE_BUTTON),
            page.locator('[role="dialog"] button').filter(has_text=NOTICE_BUTTON),
            page.get_by_role("button", name=NOTICE_BUTTON),
        ]
        button = first_visible(candidates, 500)
        if button is not None:
            notify(status, "TikTok bilgi penceresindeki 'Anladım' kapatılıyor")
            try:
                button.click(timeout=5000)
                page.wait_for_timeout(500)
                return True
            except PlaywrightError:
                pass
        # The notice is account/rollout dependent. Do not block accounts that do not receive it.
        if time.monotonic() >= optional_deadline:
            return False
        page.wait_for_timeout(400)
    return False


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
        if tag in {"input", "textarea"}:
            return field.input_value(timeout=1000).strip()
        return field.inner_text(timeout=1000).strip()
    except PlaywrightError:
        return ""


def _write_caption(field: Locator, caption: str) -> None:
    field.scroll_into_view_if_needed(timeout=3000)
    field.click(timeout=3000)
    tag = field.evaluate("el => el.tagName.toLowerCase()")
    if tag in {"input", "textarea"}:
        field.fill(caption, timeout=5000)
    else:
        try:
            field.fill(caption, timeout=5000)
        except PlaywrightError:
            field.press("ControlOrMeta+A")
            field.press("Backspace")
            field.type(caption, delay=2)
    field.evaluate(
        "el => { el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText'})); "
        "el.dispatchEvent(new Event('change', {bubbles:true})); el.blur(); }"
    )


def fill_caption(page: Page, caption: str, timeout_seconds: int = 180) -> None:
    expected = re.sub(r"\s+", " ", caption).strip()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for candidate in caption_candidates(page):
            field = first_visible([candidate], 500)
            if field is None:
                continue
            try:
                _write_caption(field, caption)
                actual = re.sub(r"\s+", " ", _caption_value(field)).strip()
                if actual == expected or expected in actual:
                    return
            except PlaywrightError:
                continue
        page.wait_for_timeout(1000)
    raise UploadError("Caption alanı bulundu ama metin doğrulanamadı; TikTok editörü değişmiş olabilir")


def publish_candidates(page: Page) -> list[Locator]:
    return [
        page.get_by_role("button", name=PUBLISH_BUTTON),
        page.locator('button[data-e2e*="post" i]'),
        page.locator('button[data-e2e*="publish" i]'),
    ]


def upload_busy(page: Page) -> bool:
    """Return True only for visible, unfinished upload/processing indicators."""
    try:
        body_text = page.locator("body").inner_text(timeout=1500)
        if UPLOAD_FAILURE.search(body_text):
            raise UploadError("TikTok videoyu reddetti: sayfadaki hata mesajını kontrol edin")
        if UPLOAD_BUSY_TEXT.search(body_text):
            return True
        bars = page.locator('[role="progressbar"]')
        for index in range(min(bars.count(), 10)):
            bar = bars.nth(index)
            if not bar.is_visible(timeout=150):
                continue
            value = bar.get_attribute("aria-valuenow")
            if value is None:
                return True
            try:
                if float(value) < 100:
                    return True
            except ValueError:
                return True
        return False
    except PlaywrightTimeout:
        return True
    except PlaywrightError:
        return True


def wait_for_upload_complete(
    page: Page,
    status: StatusCallback | None = None,
    timeout_seconds: int = 900,
) -> Locator:
    """Require a stable enabled Publish button and no active upload indicator."""
    deadline = time.monotonic() + timeout_seconds
    stable_checks = 0
    last_notice = 0.0
    while time.monotonic() < deadline:
        if page.is_closed():
            raise UploadError("TikTok penceresi upload sırasında kapatıldı")
        button = first_visible(publish_candidates(page), 400)
        enabled = False
        if button is not None:
            try:
                enabled = button.is_enabled()
            except PlaywrightError:
                enabled = False
        busy = upload_busy(page)
        if enabled and not busy:
            stable_checks += 1
            if stable_checks >= 3:
                notify(status, "Video yüklemesi tamamlandı; Paylaş düğmesi hazır")
                return button
        else:
            stable_checks = 0
        now = time.monotonic()
        if now - last_notice > 10:
            notify(status, "Video yüklemesinin tamamen bitmesi bekleniyor")
            last_notice = now
        page.wait_for_timeout(1000)
    raise UploadError("TikTok video yüklemesini 15 dakikada tamamlamadı")


def confirm_publish_dialog(page: Page) -> None:
    """Handle TikTok's optional second confirmation, scoped strictly to a dialog."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        button = first_visible([
            page.get_by_role("dialog").get_by_role("button", name=PUBLISH_CONFIRM),
            page.locator('[role="dialog"] button').filter(has_text=PUBLISH_CONFIRM),
        ], 300)
        if button is not None:
            button.click(timeout=3000)
            return
        page.wait_for_timeout(250)


def wait_for_publish_result(page: Page, timeout_seconds: int = 180) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if page.is_closed():
            raise UploadError("TikTok penceresi yayın sonucu alınmadan kapatıldı")
        try:
            text = page.locator("body").inner_text(timeout=2000)
            if UPLOAD_FAILURE.search(text):
                raise UploadError("TikTok yayını reddetti: ekrandaki hata mesajını kontrol edin")
            if PUBLISH_SUCCESS.search(text) or "tiktokstudio/upload" not in page.url.lower():
                return
        except PlaywrightTimeout:
            pass
        page.wait_for_timeout(1000)
    raise UploadError("Yayın sonucu üç dakika içinde doğrulanamadı")


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
    folder = DATA_ROOT / "profiles" / safe_profile_name(profile)
    folder.mkdir(parents=True, exist_ok=True)
    options = dict(
        user_data_dir=str(folder), headless=False, viewport=None,
        no_viewport=True, args=["--start-maximized"],
    )
    try:
        return playwright.chromium.launch_persistent_context(channel="chrome", **options)
    except PlaywrightError:
        try:
            return playwright.chromium.launch_persistent_context(**options)
        except PlaywrightError as exc:
            raise UploadError("Chrome açılamadı; `playwright install chromium` çalıştırın") from exc


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
            notify(status, f"{request.profile}: TikTok Studio açılıyor")
            page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            wait_for_upload_after_login(page, status=status)
            notify(status, f"{request.profile}: video yükleniyor")
            upload_file(page, request.video)
            dismiss_pre_caption_notice(page, status=status)
            notify(status, f"{request.profile}: caption yazılıyor")
            fill_caption(page, request.caption.strip())
            notify(status, f"{request.profile}: caption yazıldı ve doğrulandı")
            button = wait_for_upload_complete(page, status=status)
            page.bring_to_front()
            if publish:
                # --publish or the GUI batch action is the user's explicit authorization.
                # The obsolete per-profile preview prompt is intentionally skipped.
                notify(status, f"{request.profile}: Paylaş düğmesine basılıyor")
                button.click(timeout=5000)
                confirm_publish_dialog(page)
                wait_for_publish_result(page)
                notify(status, f"{request.profile}: yayın tamamlandı; sıradaki hesaba geçiliyor")
            else:
                notify(status, "Hazır: Paylaş düğmesi kullanıcıya bırakıldı")
                while context.pages:
                    page.wait_for_timeout(1000)
        except Exception as exc:
            folder = save_diagnostics(page, request.profile, exc)
            raise UploadError(f"{exc}\nTanı dosyaları: {folder}") from exc
        finally:
            context.close()


def main() -> int:
    parser = argparse.ArgumentParser()
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
    except Exception as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
