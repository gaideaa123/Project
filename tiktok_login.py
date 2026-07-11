from __future__ import annotations

"""Lower-risk profile-scoped TikTok web publishing.

This keeps the required automatic final Publish click, but removes session-cookie
injection and JavaScript-dispatched input/change events. It uses a normal visible
Chrome profile, interactive login, Playwright's standard input actions and the
existing explicit GUI approval before publication. No stealth/fingerprint patches
or anti-bot bypasses are installed.
"""

import re
import threading
import time
from typing import Any

import keyring
from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

import copyright_dialog
import preflight_hook
import tiktok_overlays

SERVICE = "signaldesk-tiktok-web-login"
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=creator_center"
_INSTALL_LOCK = threading.RLock()


class LoginError(RuntimeError):
    pass


def _key(profile, field):
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "-", profile.strip()).strip("-.")[:80]
    if not clean:
        raise LoginError("Profil adı geçersiz")
    return f"{clean}:{field}"


def _session_value(raw):
    value = raw.strip()
    match = re.search(r"(?:^|;\s*)sessionid=([^;\s]+)", value, re.I)
    if match:
        value = match.group(1)
    if not value or len(value) < 16 or re.search(r"\s", value):
        raise LoginError("Geçerli bir TikTok sessionid girin")
    return value


def save_session(profile, value):
    """Legacy UI compatibility only; automatic publishing never injects it."""
    keyring.set_password(SERVICE, _key(profile, "sessionid"), _session_value(value))


def load_session(profile):
    try:
        return keyring.get_password(SERVICE, _key(profile, "sessionid")) or ""
    except Exception:
        return ""


def has_session(profile):
    return bool(load_session(profile))


def delete_session(profile):
    try:
        keyring.delete_password(SERVICE, _key(profile, "sessionid"))
    except Exception:
        pass


def save_credentials(profile, identity, password):
    if not identity.strip() or not password:
        raise LoginError("Kullanıcı ve parola birlikte girilmeli")
    keyring.set_password(SERVICE, _key(profile, "identity"), identity.strip())
    keyring.set_password(SERVICE, _key(profile, "password"), password)


def load_credentials(profile):
    try:
        return (
            keyring.get_password(SERVICE, _key(profile, "identity")) or "",
            keyring.get_password(SERVICE, _key(profile, "password")) or "",
        )
    except Exception:
        return "", ""


def has_credentials(profile):
    identity, password = load_credentials(profile)
    return bool(identity and password)


def _visible(locator, timeout=400):
    try:
        return bool(locator.count() and locator.first.is_visible(timeout=timeout))
    except (PlaywrightTimeout, PlaywrightError):
        return False


def locator_attached(locator) -> bool:
    try:
        return locator.count() > 0
    except PlaywrightError:
        return False


def file_input_ready(page) -> bool:
    try:
        return locator_attached(page.locator('input[type="file"]'))
    except PlaywrightError:
        return False


def wait_for_upload_after_login(page, timeout_seconds=900, status=None, profile=""):
    """Require TikTok's normal interactive login in the persistent Chrome profile."""
    deadline = time.monotonic() + timeout_seconds
    login_reported = False
    last_navigation = 0.0
    while time.monotonic() < deadline:
        if page.is_closed():
            raise LoginError("TikTok penceresi kapatıldı")
        if file_input_ready(page):
            if status:
                status("Normal Chrome oturumu hazır; upload ekranı açıldı")
            return
        url = page.url.lower()
        now = time.monotonic()
        if "/login" in url or _visible(page.locator('input[type="password"]')):
            if not login_reported and status:
                status(f"{profile}: TikTok girişini Chrome içinde normal şekilde tamamlayın")
            login_reported = True
            page.bring_to_front()
            page.wait_for_timeout(750)
            continue
        if "tiktokstudio/upload" not in url and now - last_navigation > 4:
            try:
                page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            except PlaywrightTimeout:
                pass
            last_navigation = now
            continue
        page.wait_for_timeout(750)
    raise LoginError("TikTok giriş/upload ekranı 15 dakikada hazır olmadı")


def _native_caption_write(field, caption: str) -> None:
    """Use Playwright input actions only; never dispatch JavaScript DOM events."""
    field.scroll_into_view_if_needed(timeout=3000)
    field.click(timeout=3000)
    tag = str(field.evaluate("el => el.tagName.toLowerCase()"))
    if tag in {"input", "textarea"}:
        field.fill("")
        field.press_sequentially(caption, delay=8)
    else:
        field.press("ControlOrMeta+A")
        field.press("Backspace")
        field.press_sequentially(caption, delay=8)
    field.press("Tab")


def handle_copyright_publish_dialog(page, timeout_seconds: float = 20.0) -> bool:
    return copyright_dialog.handle(page, timeout_seconds)


def install(web_uploader: Any):
    """Install automatic publishing with reduced, honest automation surface."""
    with _INSTALL_LOCK:
        if getattr(web_uploader, "_signaldesk_login_installed", False):
            preflight_hook.install(web_uploader)
            return

        original_prepare = web_uploader.prepare_upload
        original_confirm = web_uploader.confirm_publish_dialog
        original_notice = web_uploader.dismiss_pre_caption_notice
        original_caption_write = web_uploader._write_caption
        web_uploader.file_input_ready = file_input_ready

        def confirm_for_every_profile(page):
            if handle_copyright_publish_dialog(page):
                return
            original_confirm(page)

        def dismiss_pre_caption_notice(page, status=None, timeout_seconds=45, optional_after_seconds=8):
            tiktok_overlays.clear_new_account_overlays(
                page, status=status, timeout_seconds=12, quiet_seconds=1.2
            )
            result = original_notice(
                page, status=status, timeout_seconds=timeout_seconds,
                optional_after_seconds=optional_after_seconds,
            )
            tiktok_overlays.clear_new_account_overlays(
                page, status=status, timeout_seconds=12, quiet_seconds=1.2
            )
            return result

        def prepare(request, publish=False, approval=None, status=None):
            # The current app_tr workflow is sequential. Locking also prevents a
            # future parallel call from exchanging profile-specific wrappers.
            with _INSTALL_LOCK:
                original_wait = web_uploader.wait_for_upload_after_login
                previous_confirm = web_uploader.confirm_publish_dialog
                previous_writer = web_uploader._write_caption

                def waiter(page, timeout_seconds=900, status=None):
                    result = wait_for_upload_after_login(
                        page, timeout_seconds, status, request.profile
                    )
                    tiktok_overlays.clear_new_account_overlays(
                        page, status=status, timeout_seconds=20, quiet_seconds=1.5
                    )
                    return result

                web_uploader.wait_for_upload_after_login = waiter
                web_uploader.confirm_publish_dialog = confirm_for_every_profile
                web_uploader._write_caption = _native_caption_write
                if status:
                    status(
                        f"{request.profile}: normal Chrome oturumu kullanılıyor; "
                        "GUI onayından sonra Yayınla otomatik tıklanacak"
                    )
                try:
                    # Preserve app_tr's required automatic final click and approval.
                    return original_prepare(
                        request, publish=publish, approval=approval, status=status
                    )
                finally:
                    web_uploader.wait_for_upload_after_login = original_wait
                    web_uploader.confirm_publish_dialog = previous_confirm
                    web_uploader._write_caption = previous_writer

        web_uploader.confirm_publish_dialog = confirm_for_every_profile
        web_uploader.dismiss_pre_caption_notice = dismiss_pre_caption_notice
        web_uploader._write_caption = _native_caption_write
        web_uploader.prepare_upload = prepare
        web_uploader._signaldesk_login_installed = True
        web_uploader._signaldesk_automatic_publish = True
        preflight_hook.install(web_uploader)
