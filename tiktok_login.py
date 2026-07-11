from __future__ import annotations

"""Low-risk profile-scoped TikTok web assistance.

The application may prepare a video and caption in visible Chrome, but it does
not inject session cookies or click the final Publish control. The operator uses
TikTok's normal UI for login, audience review, content checks and publication.
"""

import re
import threading
import time
from typing import Any

import keyring
from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

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
    """Retain existing UI compatibility; assisted mode never injects this value."""
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
    """Wait for a normal interactive login in the persistent Chrome profile."""
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


def install(web_uploader: Any):
    """Install assisted mode without stealth patches or cookie injection."""
    with _INSTALL_LOCK:
        if getattr(web_uploader, "_signaldesk_login_installed", False):
            preflight_hook.install(web_uploader)
            return

        original_prepare = web_uploader.prepare_upload
        original_notice = web_uploader.dismiss_pre_caption_notice
        web_uploader.file_input_ready = file_input_ready

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
            # Serialize profiles and replace only the login waiter temporarily.
            with _INSTALL_LOCK:
                original_wait = web_uploader.wait_for_upload_after_login

                def waiter(page, timeout_seconds=900, status=None):
                    result = wait_for_upload_after_login(
                        page, timeout_seconds, status, request.profile
                    )
                    tiktok_overlays.clear_new_account_overlays(
                        page, status=status, timeout_seconds=20, quiet_seconds=1.5
                    )
                    return result

                web_uploader.wait_for_upload_after_login = waiter
                if status:
                    status(
                        f"{request.profile}: düşük riskli mod. Video ve caption hazırlanacak; "
                        "görünürlük ve Yayınla işlemini Chrome'da siz tamamlayın, sonra pencereyi kapatın."
                    )
                try:
                    # publish=False is intentional. The visible browser remains open,
                    # allowing a normal human final review and click. Closing it moves
                    # the existing sequential worker to the next account.
                    return original_prepare(
                        request, publish=False, approval=None, status=status
                    )
                finally:
                    web_uploader.wait_for_upload_after_login = original_wait

        web_uploader.dismiss_pre_caption_notice = dismiss_pre_caption_notice
        web_uploader.prepare_upload = prepare
        web_uploader._signaldesk_login_installed = True
        web_uploader._signaldesk_assisted_mode = True
        preflight_hook.install(web_uploader)
