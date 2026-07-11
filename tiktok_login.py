from __future__ import annotations

import re,threading,time
from pathlib import Path
from typing import Any
import keyring
from playwright.sync_api import Error as PlaywrightError,TimeoutError as PlaywrightTimeout
import copyright_dialog,network_identity,preflight_hook,profile_integrity,proxy_health,publication_guard,publication_pacing,tiktok_overlays
SERVICE="signaldesk-tiktok-web-login";UPLOAD_URL="https://www.tiktok.com/tiktokstudio/upload?from=creator_center";_INSTALL_LOCK=threading.RLock()
class LoginError(RuntimeError):pass
def _key(p,f):
    c=re.sub(r"[^a-zA-Z0-9_.-]+","-",p.strip()).strip("-.")[:80]
    if not c:raise LoginError("Profil adı geçersiz")
    return f"{c}:{f}"
def _session_value(raw):
    value=raw.strip();m=re.search(r"(?:^|;\s*)sessionid=([^;\s]+)",value,re.I);value=m.group(1) if m else value
    if not value or len(value)<16 or re.search(r"\s",value):raise LoginError("Geçerli sessionid girin")
    return value
def save_session(p,v):keyring.set_password(SERVICE,_key(p,"sessionid"),_session_value(v))
def load_session(p):
    try:return keyring.get_password(SERVICE,_key(p,"sessionid")) or ""
    except Exception:return ""
def has_session(p):return bool(load_session(p))
def delete_session(p):
    try:keyring.delete_password(SERVICE,_key(p,"sessionid"))
    except Exception:pass
def save_credentials(p,i,w):keyring.set_password(SERVICE,_key(p,"identity"),i);keyring.set_password(SERVICE,_key(p,"password"),w)
def load_credentials(p):
    try:return keyring.get_password(SERVICE,_key(p,"identity")) or "",keyring.get_password(SERVICE,_key(p,"password")) or ""
    except Exception:return "",""
def has_credentials(p):return all(load_credentials(p))
def _visible(l,t=400):
    try:return bool(l.count() and l.first.is_visible(timeout=t))
    except Exception:return False
def file_input_ready(page):
    try:return page.locator('input[type="file"]').count()>0
    except PlaywrightError:return False
def _existing_session(context):
    try:
        for c in context.cookies(["https://www.tiktok.com"]):
            if c.get("name") in {"sessionid","sessionid_ss"} and c.get("value"):return str(c["value"])
    except PlaywrightError:pass
    return ""
def bootstrap_session(context,p):
    if _existing_session(context):return False
    sid=load_session(p)
    if not sid:return False
    context.add_cookies([{"name":"sessionid","value":sid,"domain":".tiktok.com","path":"/","secure":True,"httpOnly":True,"sameSite":"Lax"}]);return True
def wait_for_upload_after_login(page,timeout_seconds=900,status=None,profile=""):
    deadline=time.monotonic()+timeout_seconds
    while time.monotonic()<deadline:
        if page.is_closed():raise LoginError("TikTok penceresi kapatıldı")
        if file_input_ready(page):return
        if "/login" in page.url.lower() or _visible(page.locator('input[type="password"]')):page.bring_to_front();page.wait_for_timeout(750);continue
        try:page.goto(UPLOAD_URL,wait_until="domcontentloaded",timeout=90000)
        except PlaywrightTimeout:pass
    raise LoginError("TikTok giriş ekranı hazır olmadı")
def _write(field,caption):
    field.click();field.press("ControlOrMeta+A");field.press("Backspace");field.press_sequentially(caption,delay=8);field.press("Tab")
def install(web_uploader:Any):
    with _INSTALL_LOCK:
        if getattr(web_uploader,"_signaldesk_login_installed",False):preflight_hook.install(web_uploader);return
        ol=web_uploader.launch_context;op=web_uploader.prepare_upload;oc=web_uploader.confirm_publish_dialog;on=web_uploader.dismiss_pre_caption_notice;or_=web_uploader.wait_for_upload_complete
        def launch(playwright,profile):
            context=ol(playwright,profile);identity=network_identity.load(profile);health=proxy_health.verify_browser_context(context,identity) if identity.server else None;profile_dir=Path(web_uploader.DATA_ROOT)/"profiles"/web_uploader.safe_profile_name(profile);profile_integrity.verify(profile,profile_dir,proxy_health.fingerprint(identity) if identity.server else "direct",health.country_code if health else "",load_session(profile));bootstrap_session(context,profile);return context
        def confirm(page):
            if copyright_dialog.handle(page):return
            oc(page)
        def notice(page,status=None,timeout_seconds=45,optional_after_seconds=8):tiktok_overlays.clear_new_account_overlays(page,status=status);return on(page,status=status,timeout_seconds=timeout_seconds,optional_after_seconds=optional_after_seconds)
        def ready(page,status=None,timeout_seconds=900):button=or_(page,status=status,timeout_seconds=timeout_seconds);publication_guard.assert_publishable(page,status);return button
        def prepare(request,publish=False,approval=None,status=None):
            publication_pacing.wait_before(request.profile,status);attempt=0
            while True:
                try:
                    result=_prepare_once(request,publish,approval,status);publication_pacing.mark_completed(request.profile);return result
                except Exception as exc:
                    publication_pacing.register_failure(request.profile,exc)
                    if not publication_pacing.should_retry(exc,attempt):raise
                    delay=publication_pacing.retry_delay(attempt);attempt+=1
                    if status:status(f"{request.profile}: geçici ağ hatası, {delay} sn sonra sınırlı retry")
                    time.sleep(delay)
        def _prepare_once(request,publish,approval,status):
            ow=web_uploader.wait_for_upload_after_login;oldc=web_uploader.confirm_publish_dialog;oldw=web_uploader._write_caption;oldr=web_uploader.wait_for_publish_result
            def waiter(page,timeout_seconds=900,status=None):return wait_for_upload_after_login(page,timeout_seconds,status,request.profile)
            def verified(page,timeout_seconds=180):return publication_guard.wait_for_verified_publication(page,request.profile,status,timeout_seconds)
            web_uploader.wait_for_upload_after_login=waiter;web_uploader.confirm_publish_dialog=confirm;web_uploader._write_caption=_write;web_uploader.wait_for_publish_result=verified
            try:return op(request,publish=publish,approval=approval,status=status)
            finally:web_uploader.wait_for_upload_after_login=ow;web_uploader.confirm_publish_dialog=oldc;web_uploader._write_caption=oldw;web_uploader.wait_for_publish_result=oldr
        web_uploader.launch_context=launch;web_uploader.confirm_publish_dialog=confirm;web_uploader.dismiss_pre_caption_notice=notice;web_uploader.wait_for_upload_complete=ready;web_uploader.prepare_upload=prepare;web_uploader._signaldesk_login_installed=True;preflight_hook.install(web_uploader)
