from __future__ import annotations

import re,threading,time
from typing import Any
import keyring
from playwright.sync_api import Error as PlaywrightError,TimeoutError as PlaywrightTimeout
import copyright_dialog,preflight_hook,publication_guard,publication_pacing,tiktok_overlays
SERVICE="signaldesk-tiktok-web-login"; UPLOAD_URL="https://www.tiktok.com/tiktokstudio/upload?from=creator_center"; _INSTALL_LOCK=threading.RLock()
class LoginError(RuntimeError): pass
def _key(profile,field):
    clean=re.sub(r"[^a-zA-Z0-9_.-]+","-",profile.strip()).strip("-.")[:80]
    if not clean: raise LoginError("Profil adı geçersiz")
    return f"{clean}:{field}"
def _session_value(raw):
    value=raw.strip(); match=re.search(r"(?:^|;\s*)sessionid=([^;\s]+)",value,re.I); value=match.group(1) if match else value
    if not value or len(value)<16 or re.search(r"\s",value): raise LoginError("Geçerli bir TikTok sessionid girin")
    return value
def save_session(profile,value): keyring.set_password(SERVICE,_key(profile,"sessionid"),_session_value(value))
def load_session(profile):
    try:return keyring.get_password(SERVICE,_key(profile,"sessionid")) or ""
    except Exception:return ""
def has_session(profile):return bool(load_session(profile))
def delete_session(profile):
    try:keyring.delete_password(SERVICE,_key(profile,"sessionid"))
    except Exception:pass
def save_credentials(profile,identity,password):
    if not identity.strip() or not password:raise LoginError("Kullanıcı ve parola birlikte girilmeli")
    keyring.set_password(SERVICE,_key(profile,"identity"),identity.strip());keyring.set_password(SERVICE,_key(profile,"password"),password)
def load_credentials(profile):
    try:return keyring.get_password(SERVICE,_key(profile,"identity")) or "",keyring.get_password(SERVICE,_key(profile,"password")) or ""
    except Exception:return "",""
def has_credentials(profile):return all(load_credentials(profile))
def _visible(locator,timeout=400):
    try:return bool(locator.count() and locator.first.is_visible(timeout=timeout))
    except (PlaywrightTimeout,PlaywrightError):return False
def file_input_ready(page):
    try:return page.locator('input[type="file"]').count()>0
    except PlaywrightError:return False
def _existing_session_cookie(context):
    try:
        for cookie in context.cookies(["https://www.tiktok.com"]):
            if cookie.get("name") in {"sessionid","sessionid_ss"} and cookie.get("value"):return str(cookie["value"])
    except PlaywrightError:pass
    return ""
def bootstrap_session(context,profile):
    if _existing_session_cookie(context):return False
    session_id=load_session(profile)
    if not session_id:return False
    context.add_cookies([{"name":"sessionid","value":session_id,"domain":".tiktok.com","path":"/","secure":True,"httpOnly":True,"sameSite":"Lax"}]);return True
def wait_for_upload_after_login(page,timeout_seconds=900,status=None,profile=""):
    deadline=time.monotonic()+timeout_seconds;reported=False;nav=0.0
    while time.monotonic()<deadline:
        if page.is_closed():raise LoginError("TikTok penceresi kapatıldı")
        if file_input_ready(page):
            if status:status("Kalıcı Chrome profili doğrulandı; upload hazır")
            return
        url=page.url.lower();now=time.monotonic()
        if "/login" in url or _visible(page.locator('input[type="password"]')):
            if not reported and status:status(f"{profile}: ek doğrulama gerekiyor")
            reported=True;page.bring_to_front();page.wait_for_timeout(750);continue
        if "tiktokstudio/upload" not in url and now-nav>4:
            try:page.goto(UPLOAD_URL,wait_until="domcontentloaded",timeout=90000)
            except PlaywrightTimeout:pass
            nav=now;continue
        page.wait_for_timeout(750)
    raise LoginError("TikTok session/giriş/upload ekranı hazır olmadı")
def _native_caption_write(field,caption):
    field.scroll_into_view_if_needed(timeout=3000);field.click(timeout=3000);tag=str(field.evaluate("el => el.tagName.toLowerCase()"))
    if tag in {"input","textarea"}:field.fill("");field.press_sequentially(caption,delay=8)
    else:field.press("ControlOrMeta+A");field.press("Backspace");field.press_sequentially(caption,delay=8)
    field.press("Tab")
def install(web_uploader:Any):
    with _INSTALL_LOCK:
        if getattr(web_uploader,"_signaldesk_login_installed",False):preflight_hook.install(web_uploader);return
        original_launch=web_uploader.launch_context;original_prepare=web_uploader.prepare_upload;original_confirm=web_uploader.confirm_publish_dialog;original_notice=web_uploader.dismiss_pre_caption_notice;original_ready=web_uploader.wait_for_upload_complete
        def launch(playwright,profile):context=original_launch(playwright,profile);bootstrap_session(context,profile);return context
        def confirm(page):
            if copyright_dialog.handle(page):return
            original_confirm(page)
        def notice(page,status=None,timeout_seconds=45,optional_after_seconds=8):
            tiktok_overlays.clear_new_account_overlays(page,status=status,timeout_seconds=12,quiet_seconds=1.2);result=original_notice(page,status=status,timeout_seconds=timeout_seconds,optional_after_seconds=optional_after_seconds);tiktok_overlays.clear_new_account_overlays(page,status=status,timeout_seconds=12,quiet_seconds=1.2);return result
        def ready(page,status=None,timeout_seconds=900):button=original_ready(page,status=status,timeout_seconds=timeout_seconds);publication_guard.assert_publishable(page,status);return button
        def prepare(request,publish=False,approval=None,status=None):
            with _INSTALL_LOCK:
                publication_pacing.wait_before(request.profile,status);old_wait=web_uploader.wait_for_upload_after_login;old_confirm=web_uploader.confirm_publish_dialog;old_writer=web_uploader._write_caption;old_result=web_uploader.wait_for_publish_result
                def waiter(page,timeout_seconds=900,status=None):result=wait_for_upload_after_login(page,timeout_seconds,status,request.profile);tiktok_overlays.clear_new_account_overlays(page,status=status,timeout_seconds=20,quiet_seconds=1.5);return result
                def verified(page,timeout_seconds=180):return publication_guard.wait_for_verified_publication(page,request.profile,status,timeout_seconds)
                web_uploader.wait_for_upload_after_login=waiter;web_uploader.confirm_publish_dialog=confirm;web_uploader._write_caption=_native_caption_write;web_uploader.wait_for_publish_result=verified
                try:
                    result=original_prepare(request,publish=publish,approval=approval,status=status)
                    if publish:publication_pacing.mark_completed()
                    return result
                finally:web_uploader.wait_for_upload_after_login=old_wait;web_uploader.confirm_publish_dialog=old_confirm;web_uploader._write_caption=old_writer;web_uploader.wait_for_publish_result=old_result
        web_uploader.launch_context=launch;web_uploader.confirm_publish_dialog=confirm;web_uploader.dismiss_pre_caption_notice=notice;web_uploader.wait_for_upload_complete=ready;web_uploader._write_caption=_native_caption_write;web_uploader.prepare_upload=prepare;web_uploader._signaldesk_login_installed=True;preflight_hook.install(web_uploader)
