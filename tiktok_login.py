from __future__ import annotations

"""Secure TikTok login assistance for a visible Playwright browser.

Credentials live in the operating-system keychain. This module never bypasses
CAPTCHA, 2FA, device verification, or consent; those remain visible to the user.
"""

import re
import time
from collections.abc import Callable
from typing import Any

import keyring
from playwright.sync_api import Error as PlaywrightError, Page, TimeoutError as PlaywrightTimeout

SERVICE = "signaldesk-tiktok-web-login"
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=creator_center"
StatusCallback = Callable[[str], None]


class LoginError(RuntimeError):
    pass


def _key(profile: str, field: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", profile.strip()).strip("-.")[:80]
    if not normalized:
        raise LoginError("Profil adı geçersiz")
    return f"{normalized}:{field}"


def save_credentials(profile: str, identity: str, password: str) -> None:
    if not identity.strip() or not password:
        raise LoginError("TikTok kullanıcı adı/e-posta ve parola zorunlu")
    keyring.set_password(SERVICE, _key(profile, "identity"), identity.strip())
    keyring.set_password(SERVICE, _key(profile, "password"), password)


def load_credentials(profile: str) -> tuple[str, str]:
    return (
        keyring.get_password(SERVICE, _key(profile, "identity")) or "",
        keyring.get_password(SERVICE, _key(profile, "password")) or "",
    )


def delete_credentials(profile: str) -> None:
    for field in ("identity", "password"):
        try:
            keyring.delete_password(SERVICE, _key(profile, field))
        except Exception:
            pass


def has_credentials(profile: str) -> bool:
    identity, password = load_credentials(profile)
    return bool(identity and password)


def _notify(callback: StatusCallback | None, message: str) -> None:
    if callback:
        callback(message)


def _visible(locator: Any, timeout: int = 400) -> bool:
    try:
        return bool(locator.count() and locator.first.is_visible(timeout=timeout))
    except (PlaywrightTimeout, PlaywrightError):
        return False


def _file_input_ready(page: Page) -> bool:
    try:
        field = page.locator('input[type="file"]')
        return bool(field.count() and field.first.is_attached())
    except PlaywrightError:
        return False


def _challenge_visible(page: Page) -> bool:
    patterns = re.compile(
        r"captcha|verify|verification|security check|two-step|2-step|"
        r"doğrulama|güvenlik kontrolü|kodu gir|enter code",
        re.I,
    )
    try:
        text = page.locator("body").inner_text(timeout=1200)
        return bool(patterns.search(text))
    except PlaywrightError:
        return False


def _open_identity_login(page: Page) -> None:
    candidates = [
        page.get_by_text(re.compile(r"use phone.*email.*username|telefon.*e-posta.*kullanıcı", re.I)),
        page.get_by_text(re.compile(r"email.*username|e-posta.*kullanıcı", re.I)),
        page.get_by_role("button", name=re.compile(r"email|username|e-posta|kullanıcı", re.I)),
    ]
    for candidate in candidates:
        if _visible(candidate):
            try:
                candidate.first.click()
                page.wait_for_timeout(500)
                return
            except PlaywrightError:
                continue


def _fill_and_submit(page: Page, identity: str, password: str) -> bool:
    _open_identity_login(page)
    identity_fields = [
        page.locator('input[name="username"]'),
        page.locator('input[autocomplete="username"]'),
        page.locator('input[placeholder*="email" i]'),
        page.locator('input[placeholder*="username" i]'),
        page.locator('input[placeholder*="e-posta" i]'),
        page.locator('input[type="text"]'),
    ]
    password_field = page.locator('input[type="password"]')
    identity_field = next((item.first for item in identity_fields if _visible(item)), None)
    if identity_field is None or not _visible(password_field):
        return False
    try:
        identity_field.fill(identity)
        password_field.first.fill(password)
        submit = page.get_by_role("button", name=re.compile(r"^log in$|^sign in$|^giriş yap$", re.I))
        if _visible(submit):
            submit.first.click()
        else:
            password_field.first.press("Enter")
        return True
    except PlaywrightError:
        return False


def wait_for_upload_after_login(
    page: Page,
    timeout_seconds: int = 900,
    status: StatusCallback | None = None,
    profile: str = "",
) -> None:
    """Reuse session, auto-fill saved credentials, then resume Studio upload."""
    deadline = time.monotonic() + timeout_seconds
    identity, password = load_credentials(profile) if profile else ("", "")
    attempted = False
    challenge_notified = False
    last_navigation = 0.0

    while time.monotonic() < deadline:
        if page.is_closed():
            raise LoginError("TikTok penceresi kapatıldı")
        if _file_input_ready(page):
            _notify(status, "TikTok oturumu hazır; video yükleme ekranı açıldı")
            return

        now = time.monotonic()
        url = page.url.lower()
        if _challenge_visible(page):
            if not challenge_notified:
                _notify(status, "TikTok CAPTCHA/2FA doğrulamasını tarayıcıda tamamlayın")
                challenge_notified = True
            page.bring_to_front()
            page.wait_for_timeout(750)
            continue

        login_visible = "/login" in url or _visible(page.locator('input[type="password"]'))
        if login_visible:
            if identity and password and not attempted:
                _notify(status, "Kayıtlı TikTok giriş bilgileri güvenli kasadan dolduruluyor")
                attempted = _fill_and_submit(page, identity, password)
                page.wait_for_timeout(1200)
                continue
            message = (
                "Otomatik giriş başarısız; TikTok girişini tarayıcıda tamamlayın"
                if attempted else
                "Bu profil için giriş bilgisi kayıtlı değil; GUI'deki Giriş Kaydet düğmesini kullanın"
            )
            _notify(status, message)
            page.bring_to_front()
            page.wait_for_timeout(1000)
            continue

        if "tiktokstudio/upload" not in url and now - last_navigation > 4:
            _notify(status, "Oturum algılandı; TikTok Studio yükleme ekranına dönülüyor")
            try:
                page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            except PlaywrightTimeout:
                pass
            last_navigation = now
            continue
        page.wait_for_timeout(750)

    raise LoginError("TikTok girişi veya yükleme ekranı 15 dakika içinde tamamlanmadı")


def install(web_uploader: Any) -> None:
    """Install the profile-aware login waiter without coupling the uploader to keyring."""
    original_prepare = web_uploader.prepare_upload

    def prepare_upload(request: Any, publish: bool = False, approval=None, status=None) -> None:
        original_wait = web_uploader.wait_for_upload_after_login

        def waiter(page: Page, timeout_seconds: int = 900, status=None) -> None:
            wait_for_upload_after_login(page, timeout_seconds, status, request.profile)

        web_uploader.wait_for_upload_after_login = waiter
        try:
            original_prepare(request, publish=publish, approval=approval, status=status)
        finally:
            web_uploader.wait_for_upload_after_login = original_wait

    web_uploader.prepare_upload = prepare_upload
