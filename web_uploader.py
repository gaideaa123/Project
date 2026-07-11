from __future__ import annotations

"""Visible, user-confirmed TikTok Studio upload assistant.

This module does not bypass login, CAPTCHA, 2FA, platform review, or the final
Publish confirmation. It opens a normal persistent Chromium profile, uploads
one local video, fills its caption, then leaves the browser open for review.
"""

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from platformdirs import user_data_dir
from playwright.sync_api import (
    BrowserContext,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
    sync_playwright,
)

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=creator_center"
DATA_ROOT = Path(user_data_dir("signaldesk-web-uploader", "SignalDesk"))
MEDIA_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}


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
        if self.video.stat().st_size == 0:
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


def locator_attached(locator: Locator) -> bool:
    """Use the public Playwright API instead of the removed is_attached helper."""
    try:
        return locator.count() > 0
    except Exception:
        return False


def first_visible(locators: Iterable[Locator], timeout_ms: int = 1500) -> Locator | None:
    for locator in locators:
        try:
            if locator.first.is_visible(timeout=timeout_ms):
                return locator.first
        except PlaywrightTimeout:
            continue
    return None


def wait_for_login(page: Page, timeout_seconds: int = 600) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if "/login" not in page.url.lower():
            file_input = page.locator('input[type="file"]')
            if locator_attached(file_input):
                return
        page.wait_for_timeout(1000)
    raise UploadError("Giriş için 10 dakika doldu. Tarayıcıdan giriş yapıp yeniden deneyin")


def upload_file(page: Page, video: Path) -> None:
    direct = page.locator('input[type="file"]')
    try:
        if locator_attached(direct):
            direct.first.set_input_files(str(video.resolve()))
            return
    except Exception:
        pass

    buttons = [
        page.get_by_role("button", name=re.compile(r"select|upload|choose|yükle|seç", re.I)),
        page.get_by_text(re.compile(r"select video|upload video|video seç|video yükle", re.I)),
    ]
    trigger = first_visible(buttons, 2500)
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
        page.locator('[contenteditable="true"]').first,
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
                page.keyboard.press("Control+A")
                page.keyboard.insert_text(caption)
            return
        page.wait_for_timeout(1000)
    raise UploadError("Caption alanı yüklenmedi. Video işleme tamamlanmamış veya sayfa değişmiş olabilir")


def wait_until_ready(page: Page, timeout_seconds: int = 600) -> None:
    deadline = time.monotonic() + timeout_seconds
    failure = re.compile(r"upload failed|couldn't upload|yükleme başarısız|unsupported", re.I)
    while time.monotonic() < deadline:
        body = page.locator("body")
        try:
            text = body.inner_text(timeout=2000)
            if failure.search(text):
                raise UploadError("TikTok videoyu reddetti: sayfadaki hata mesajını kontrol edin")
        except PlaywrightTimeout:
            pass

        publish = first_visible(
            [
                page.get_by_role("button", name=re.compile(r"^post$|^publish$|^yayınla$|^paylaş$", re.I)),
                page.locator('button[data-e2e*="post" i]'),
            ],
            500,
        )
        if publish is not None:
            try:
                if publish.is_enabled():
                    return
            except Exception:
                pass
        page.wait_for_timeout(1500)
    raise UploadError("TikTok video işlemeyi 10 dakikada tamamlamadı")


def save_diagnostics(page: Page, profile: str, error: Exception) -> Path:
    folder = DATA_ROOT / "diagnostics" / datetime.now().strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(folder / "page.png"), full_page=True)
    except Exception:
        pass
    try:
        (folder / "page.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    (folder / "error.json").write_text(
        json.dumps(
            {
                "profile": profile,
                "url": page.url,
                "error": str(error),
                "time": datetime.now().isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return folder


def launch_context(playwright: Playwright, profile: str) -> BrowserContext:
    profile_dir = DATA_ROOT / "profiles" / safe_profile_name(profile)
    profile_dir.mkdir(parents=True, exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=False,
        channel="chrome",
        viewport=None,
        no_viewport=True,
        args=["--start-maximized"],
    )


def prepare_upload(request: UploadRequest) -> None:
    request.validate()
    with sync_playwright() as playwright:
        context = launch_context(playwright, request.profile)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            wait_for_login(page)
            upload_file(page, request.video)
            fill_caption(page, request.caption)
            wait_until_ready(page)
            page.bring_to_front()
            print("HAZIR: Video ve caption dolduruldu. TikTok ayarlarını kontrol edip Yayınla düğmesine siz basın.")
            print("Tarayıcıyı kapattığınızda işlem sona erecek.")
            while context.pages:
                page.wait_for_timeout(1000)
        except Exception as exc:
            folder = save_diagnostics(page, request.profile, exc)
            raise UploadError(f"{exc}\nTanı dosyaları: {folder}") from exc
        finally:
            context.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="TikTok Studio görünür web yükleme yardımcısı")
    parser.add_argument("--profile", required=True, help="Yerel tarayıcı profili adı")
    parser.add_argument("--video", required=True, type=Path, help="Yüklenecek video")
    parser.add_argument("--caption", help="Caption metni")
    parser.add_argument("--caption-file", type=Path, help="UTF-8 caption dosyası")
    args = parser.parse_args()
    caption = args.caption or (args.caption_file.read_text(encoding="utf-8") if args.caption_file else "")
    try:
        prepare_upload(UploadRequest(args.profile, args.video.expanduser().resolve(), caption))
        return 0
    except Exception as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
