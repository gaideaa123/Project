from __future__ import annotations

"""Profile-scoped TikTok session and visible login assistance."""

import re
import time
from typing import Any

import keyring
from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

SERVICE = "signaldesk-tiktok-web-login"
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=creator_center"

class LoginError(RuntimeError): pass

def _key(profile, field):
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "-", profile.strip()).strip("-.")[:80]
    if not clean: raise LoginError("Profil adı geçersiz")
    return f"{clean}:{field}"

def _session_value(raw):
    value = raw.strip()
    match = re.search(r"(?:^|;\s*)sessionid=([^;\s]+)", value, re.I)
    if match: value = match.group(1)
    if not value or len(value) < 16 or re.search(r"\s", value):
        raise LoginError("Geçerli bir TikTok sessionid girin")
    return value

def save_session(profile, value):
    keyring.set_password(SERVICE, _key(profile, "sessionid"), _session_value(value))

def load_session(profile):
    try: return keyring.get_password(SERVICE, _key(profile, "sessionid")) or ""
    except Exception: return ""

def has_session(profile): return bool(load_session(profile))

def delete_session(profile):
    try: keyring.delete_password(SERVICE, _key(profile, "sessionid"))
    except Exception: pass

def save_credentials(profile, identity, password):
    if not identity.strip() or not password: raise LoginError("Kullanıcı ve parola birlikte girilmeli")
    keyring.set_password(SERVICE, _key(profile, "identity"), identity.strip())
    keyring.set_password(SERVICE, _key(profile, "password"), password)

def load_credentials(profile):
    try:
        return (keyring.get_password(SERVICE, _key(profile, "identity")) or "", keyring.get_password(SERVICE, _key(profile, "password")) or "")
    except Exception: return "", ""

def has_credentials(profile):
    identity, password = load_credentials(profile); return bool(identity and password)

def _visible(locator, timeout=400):
    try: return bool(locator.count() and locator.first.is_visible(timeout=timeout))
    except (PlaywrightTimeout, PlaywrightError): return False

def _file_ready(page):
    try:
        field = page.locator('input[type="file"]'); return bool(field.count() and field.first.is_attached())
    except PlaywrightError: return False

def wait_for_upload_after_login(page, timeout_seconds=900, status=None, profile=""):
    deadline = time.monotonic() + timeout_seconds
    identity, password = load_credentials(profile)
    attempted = False; last_nav = 0.0
    while time.monotonic() < deadline:
        if page.is_closed(): raise LoginError("TikTok penceresi kapatıldı")
        if _file_ready(page):
            if status: status("TikTok oturumu doğrulandı; upload hazır")
            return
        url = page.url.lower(); now = time.monotonic()
        if "/login" in url or _visible(page.locator('input[type="password"]')):
            if identity and password and not attempted:
                attempted = True
                if status: status("Session geçersiz; kayıtlı hesapla görünür giriş gerekiyor")
            page.bring_to_front(); page.wait_for_timeout(1000); continue
        if "tiktokstudio/upload" not in url and now - last_nav > 4:
            try: page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            except PlaywrightTimeout: pass
            last_nav = now; continue
        page.wait_for_timeout(750)
    raise LoginError("TikTok session/giriş doğrulaması tamamlanmadı")

def install(web_uploader: Any):
    if getattr(web_uploader, "_signaldesk_login_installed", False): return
    original_launch, original_prepare = web_uploader.launch_context, web_uploader.prepare_upload
    def launch(playwright, profile):
        context = original_launch(playwright, profile)
        session_id = load_session(profile)
        if session_id:
            context.add_cookies([{"name":"sessionid","value":session_id,"domain":".tiktok.com","path":"/","secure":True,"httpOnly":True,"sameSite":"Lax"}])
        return context
    def prepare(request, publish=False, approval=None, status=None):
        original_wait = web_uploader.wait_for_upload_after_login
        def waiter(page, timeout_seconds=900, status=None):
            return wait_for_upload_after_login(page, timeout_seconds, status, request.profile)
        web_uploader.wait_for_upload_after_login = waiter
        try: return original_prepare(request, publish=publish, approval=approval, status=status)
        finally: web_uploader.wait_for_upload_after_login = original_wait
    web_uploader.launch_context = launch
    web_uploader.prepare_upload = prepare
    web_uploader._signaldesk_login_installed = True
