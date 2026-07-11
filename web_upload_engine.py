from __future__ import annotations

"""Visible, user-confirmed TikTok Studio upload assistant.

This flow never bypasses login, CAPTCHA, 2FA, review, or user confirmation.
Interaction timing is used for reliable caption entry, not fingerprint hiding.
"""

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from platformdirs import user_data_dir
from playwright.sync_api import BrowserContext, Locator, Page, TimeoutError as PlaywrightTimeout, sync_playwright

from utils.antibot_resilience import InteractionConfig, human_typing_locator
from utils.network_identity import apply_test_page_defaults

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=creator_center"
DATA_ROOT = Path(user_data_dir("signaldesk-web-uploader", "SignalDesk"))
MEDIA_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
CAPTION_INTERACTION = InteractionConfig(
    min_key_delay_ms=20,
    max_key_delay_ms=70,
    pause_probability=0.02,
    min_pause_ms=100,
    max_pause_ms=250,
    timeout_ms=10_000,
)


class WebUploadError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebUploadRequest:
    profile_name: str
    video: Path
    caption: str

    def validate(self) -> None:
        if not self.profile_name.strip():
            raise WebUploadError("Tarayıcı profil adı boş")
        if not self.video.is_file() or self.video.suffix.lower() not in MEDIA_EXTENSIONS:
            raise WebUploadError(f"Geçerli video bulunamadı: {self.video}")
        if self.video.stat().st_size <= 0:
            raise WebUploadError("Video dosyası boş")
        if not self.caption.strip():
            raise WebUploadError("Caption boş")
        if len(self.caption) > 2200:
            raise WebUploadError("Caption 2200 karakter sınırını aşıyor")


def safe_name(value: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-.")
    if not result:
        raise WebUploadError("Tarayıcı profil adı geçersiz")
    return result[:80]


def first_visible(locators: Iterable[Locator], timeout_ms: int = 900) -> Locator | None:
    for locator in locators:
        try:
            candidate = locator.first
            if candidate.is_visible(timeout=timeout_ms):
                return candidate
        except Exception:
            continue
    return None


def diagnostics(page: Page, profile: str, error: Exception) -> Path:
    folder = DATA_ROOT / "diagnostics" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    folder.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(folder / "page.png"), full_page=True)
    except Exception:
        pass
    try:
        (folder / "page.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    (folder / "error.json").write_text(json.dumps({
        "profile": profile,
        "url": page.url,
        "error": str(error),
        "time": datetime.now().isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


def launch_context(playwright, profile_name: str) -> BrowserContext:
    folder = DATA_ROOT / "profiles" / safe_name(profile_name)
    folder.mkdir(parents=True, exist_ok=True)
    options = dict(
        user_data_dir=str(folder),
        headless=False,
        viewport=None,
        no_viewport=True,
        args=["--start-maximized", "--disable-notifications"],
    )
    try:
        return playwright.chromium.launch_persistent_context(channel="chrome", **options)
    except Exception:
        return playwright.chromium.launch_persistent_context(**options)


def wait_for_upload_page(page: Page, cancelled: threading.Event, status: Callable[[str], None], seconds: int = 900) -> None:
    deadline = time.monotonic() + seconds
    login_reported = False
    while time.monotonic() < deadline:
        if cancelled.is_set():
            raise WebUploadError("İşlem iptal edildi")
        try:
            file_input = page.locator('input[type="file"]')
            if file_input.count() and file_input.first.is_attached():
                return
        except Exception:
            pass
        if not login_reported:
            status("Tarayıcıda TikTok girişini, CAPTCHA veya 2FA adımını tamamlayın")
            login_reported = True
        page.wait_for_timeout(1000)
    raise WebUploadError("TikTok giriş/yükleme ekranı için 15 dakika doldu")


def set_video(page: Page, video: Path) -> None:
    direct = page.locator('input[type="file"]')
    try:
        if direct.count():
            direct.first.set_input_files(str(video.resolve()))
            return
    except Exception:
        pass
    trigger = first_visible([
        page.get_by_role("button", name=re.compile(r"select|upload|choose|yükle|seç", re.I)),
        page.get_by_text(re.compile(r"select video|upload video|video seç|video yükle", re.I)),
    ], 2000)
    if trigger is None:
        raise WebUploadError("TikTok video seçim alanı bulunamadı")
    try:
        with page.expect_file_chooser(timeout=6000) as chooser:
            trigger.click()
        chooser.value.set_files(str(video.resolve()))
    except PlaywrightTimeout as exc:
        raise WebUploadError("TikTok dosya seçiciyi açmadı") from exc


def caption_fields(page: Page) -> list[Locator]:
    return [
        page.locator('[contenteditable="true"][data-e2e*="caption" i]'),
        page.locator('[contenteditable="true"][aria-label*="caption" i]'),
        page.locator('[contenteditable="true"][aria-label*="description" i]'),
        page.get_by_role("textbox", name=re.compile(r"caption|description|açıklama", re.I)),
        page.locator('textarea[placeholder*="caption" i]'),
        page.locator('textarea[placeholder*="description" i]'),
    ]


def fill_caption(page: Page, caption: str, cancelled: threading.Event, seconds: int = 240) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cancelled.is_set():
            raise WebUploadError("İşlem iptal edildi")
        field = first_visible(caption_fields(page), 700)
        if field is not None:
            try:
                human_typing_locator(page, field, caption, config=CAPTION_INTERACTION)
                return
            except PlaywrightTimeout:
                pass
        page.wait_for_timeout(1000)
    raise WebUploadError("Caption alanı 4 dakikada yüklenmedi")


def publish_button(page: Page) -> Locator | None:
    return first_visible([
        page.get_by_role("button", name=re.compile(r"^post$|^publish$|^yayınla$|^paylaş$", re.I)),
        page.locator('button[data-e2e*="post" i]'),
        page.locator('button[data-e2e*="publish" i]'),
    ], 500)


def wait_ready(page: Page, cancelled: threading.Event, status: Callable[[str], None], seconds: int = 900) -> Locator:
    deadline = time.monotonic() + seconds
    error_pattern = re.compile(r"upload failed|couldn't upload|yükleme başarısız|unsupported format|format desteklenmiyor", re.I)
    while time.monotonic() < deadline:
        if cancelled.is_set():
            raise WebUploadError("İşlem iptal edildi")
        try:
            body_text = page.locator("body").inner_text(timeout=1500)
            if error_pattern.search(body_text):
                raise WebUploadError("TikTok videoyu reddetti; tarayıcıdaki mesajı kontrol edin")
        except PlaywrightTimeout:
            pass
        button = publish_button(page)
        if button is not None:
            try:
                if button.is_enabled():
                    return button
            except Exception:
                pass
        status("TikTok videoyu işliyor, yayın düğmesi bekleniyor")
        page.wait_for_timeout(1500)
    raise WebUploadError("TikTok video işlemeyi 15 dakikada tamamlamadı")


def wait_for_confirmation(confirm: threading.Event, cancelled: threading.Event, status: Callable[[str], None]) -> None:
    status("Hazır. Önizlemeyi kontrol edin, sonra GUI'de ONAYLA VE YAYINLA'ya basın")
    while not confirm.wait(0.25):
        if cancelled.is_set():
            raise WebUploadError("İşlem iptal edildi")


def click_publish_and_verify(page: Page, button: Locator, status: Callable[[str], None]) -> None:
    status("Yayınla tıklanıyor")
    button.scroll_into_view_if_needed()
    button.click(timeout=10000)
    success = re.compile(r"uploaded|published|scheduled|posted|yüklendi|yayınlandı|planlandı", re.I)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if success.search(page.locator("body").inner_text(timeout=1500)):
                status("TikTok yayını kabul etti")
                return
        except Exception:
            pass
        if "/upload" not in page.url.lower():
            status("TikTok yayın ekranından ayrıldı, gönderim kabul edildi")
            return
        page.wait_for_timeout(1000)
    raise WebUploadError("Yayınla tıklandı ancak başarı yanıtı doğrulanamadı; tarayıcıyı kontrol edin")


def run_upload(request: WebUploadRequest, confirm: threading.Event, cancelled: threading.Event,
               status: Callable[[str], None], ready: Callable[[], None]) -> None:
    request.validate()
    with sync_playwright() as playwright:
        context = launch_context(playwright, request.profile_name)
        page = context.pages[0] if context.pages else context.new_page()
        apply_test_page_defaults(page, timeout_ms=10_000)
        try:
            status("TikTok Studio açılıyor")
            page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            wait_for_upload_page(page, cancelled, status)
            status(f"Video seçiliyor: {request.video.name}")
            set_video(page, request.video)
            status("Caption dolduruluyor")
            fill_caption(page, request.caption, cancelled)
            button = wait_ready(page, cancelled, status)
            page.bring_to_front()
            ready()
            wait_for_confirmation(confirm, cancelled, status)
            click_publish_and_verify(page, button, status)
        except Exception as exc:
            folder = diagnostics(page, request.profile_name, exc)
            raise WebUploadError(f"{exc}\nTanı klasörü: {folder}") from exc
        finally:
            context.close()
