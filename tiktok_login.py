from __future__ import annotations

"""Profile-scoped TikTok session and visible login assistance."""

import re
import time
from typing import Any

import keyring
from playwright.sync_api import Error as PlaywrightError, Page, TimeoutError as PlaywrightTimeout

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

def save_session(profile, session_id):
    keyring.set_password(SERVICE, _key(profile, "sessionid"), _session_value(session_id))

def load_session(profile):
    return keyring.get_password(SERVICE, _key(profile, "sessionid")) or ""

def delete_session(profile):
    try: keyring.delete_password(SERVICE, _key(profile, "sessionid"))
    except keyring.errors.PasswordDeleteError: pass

def save_credentials(profile, identity, password):
    if identity.strip().casefold() in {"sessionid", "session", "cookie"}:
        save_session(profile, password); return
    if not identity.strip() or not password:
        raise LoginError("Kullanıcı + parola birlikte girilmeli")
    keyring.set_password(SERVICE, _key(profile, "identity"), identity.strip())
    keyring.set_password(SERVICE, _key(profile, "password"), password)

def load_credentials(profile):
    return (keyring.get_password(SERVICE, _key(profile, "identity")) or "",
            keyring.get_password(SERVICE, _key(profile, "password")) or "")

def has_login(profile):
    identity, password = load_credentials(profile)
    return bool(load_session(profile) or (identity and password))

def has_credentials(profile): return has_login(profile)

def _notify(callback, message):
    if callback: callback(message)

def _visible(locator, timeout=400):
    try: return bool(locator.count() and locator.first.is_visible(timeout=timeout))
    except (PlaywrightTimeout, PlaywrightError): return False

def _file_ready(page):
    try:
        field = page.locator('input[type="file"]'); return bool(field.count() and field.first.is_attached())
    except PlaywrightError: return False

def _challenge(page):
    pattern = re.compile(r"captcha|verify|verification|security check|two-step|2-step|doğrulama|güvenlik kontrolü|kodu gir|enter code", re.I)
    try: return bool(pattern.search(page.locator("body").inner_text(timeout=1200)))
    except PlaywrightError: return False

def _fill(page, identity, password):
    candidates = [page.get_by_text(re.compile(r"use phone.*email.*username|telefon.*e-posta.*kullanıcı", re.I)), page.get_by_text(re.compile(r"email.*username|e-posta.*kullanıcı", re.I))]
    for candidate in candidates:
        if _visible(candidate):
            try: candidate.first.click(); page.wait_for_timeout(500); break
            except PlaywrightError: pass
    identities = [page.locator('input[name="username"]'), page.locator('input[autocomplete="username"]'), page.locator('input[placeholder*="email" i]'), page.locator('input[placeholder*="username" i]'), page.locator('input[type="text"]')]
    pwd = page.locator('input[type="password"]'); field = next((x.first for x in identities if _visible(x)), None)
    if field is None or not _visible(pwd): return False
    try:
        field.fill(identity); pwd.first.fill(password)
        submit = page.get_by_role("button", name=re.compile(r"^log in$|^sign in$|^giriş yap$", re.I))
        submit.first.click() if _visible(submit) else pwd.first.press("Enter"); return True
    except PlaywrightError: return False

def wait_for_upload_after_login(page, timeout_seconds=900, status=None, profile=""):
    deadline = time.monotonic() + timeout_seconds
    identity, password = load_credentials(profile) if profile else ("", "")
    attempted = False; challenge_notice = False; last_nav = 0.0
    while time.monotonic() < deadline:
        if page.is_closed(): raise LoginError("TikTok penceresi kapatıldı")
        if _file_ready(page): _notify(status, "TikTok session doğrulandı; upload hazır"); return
        now = time.monotonic(); url = page.url.lower()
        if _challenge(page):
            if not challenge_notice: _notify(status, "TikTok CAPTCHA/2FA doğrulamasını tarayıcıda tamamlayın"); challenge_notice = True
            page.bring_to_front(); page.wait_for_timeout(750); continue
        if "/login" in url or _visible(page.locator('input[type="password"]')):
            if identity and password and not attempted:
                _notify(status, "Session geçersiz; kasadaki hesap bilgileri deneniyor"); attempted = _fill(page, identity, password)
                page.wait_for_timeout(1200); continue
            _notify(status, "Session kabul edilmedi; görünür TikTok girişini tamamlayın")
            page.bring_to_front(); page.wait_for_timeout(1000); continue
        if "tiktokstudio/upload" not in url and now - last_nav > 4:
            _notify(status, "Oturum algılandı; TikTok Studio'ya dönülüyor")
            try: page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            except PlaywrightTimeout: pass
            last_nav = now; continue
        page.wait_for_timeout(750)
    raise LoginError("TikTok session/giriş doğrulaması 15 dakika içinde tamamlanmadı")

def install(web_uploader: Any):
    if getattr(web_uploader, "_signaldesk_login_installed", False): return
    original_launch, original_prepare = web_uploader.launch_context, web_uploader.prepare_upload
    def launch(playwright, profile):
        context = original_launch(playwright, profile); session_id = load_session(profile)
        if session_id:
            context.add_cookies([{"name":"sessionid","value":session_id,"domain":".tiktok.com","path":"/","secure":True,"httpOnly":True,"sameSite":"Lax"}])
        return context
    def prepare(request, publish=False, approval=None, status=None):
        original_wait = web_uploader.wait_for_upload_after_login
        def waiter(page, timeout_seconds=900, status=None): wait_for_upload_after_login(page, timeout_seconds, status, request.profile)
        web_uploader.wait_for_upload_after_login = waiter
        try: return original_prepare(request, publish=publish, approval=approval, status=status)
        finally: web_uploader.wait_for_upload_after_login = original_wait
    web_uploader.launch_context = launch; web_uploader.prepare_upload = prepare; web_uploader._signaldesk_login_installed = True
