from __future__ import annotations

"""Non-destructive profile-scoped TikTok session bootstrap."""

import re
import time
from typing import Any

import keyring
from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

import copyright_dialog
import preflight_hook
import tiktok_overlays
import tiktok_session_bundle
from tiktok_login_install import accepts_parameter, optional_callable

SERVICE="signaldesk-tiktok-web-login";UPLOAD_URL="https://www.tiktok.com/tiktokstudio/upload?from=creator_center";SESSION_COOKIE_NAMES=tiktok_session_bundle.AUTH_COOKIE_NAMES
class LoginError(RuntimeError):pass

def _key(profile,field):
 clean=re.sub(r"[^a-zA-Z0-9_.-]+","-",profile.strip()).strip("-.")[:80]
 if not clean:raise LoginError("Profil adı geçersiz")
 return f"{clean}:{field}"
def _session_value(raw):
 try:return tiktok_session_bundle.parse(raw)["sessionid"]
 except ValueError as exc:raise LoginError(str(exc)) from exc
def save_session(profile,value):
 try:rows=tiktok_session_bundle.parse(value)
 except ValueError as exc:raise LoginError(str(exc)) from exc
 keyring.set_password(SERVICE,_key(profile,"cookies"),tiktok_session_bundle.dumps(rows));keyring.set_password(SERVICE,_key(profile,"sessionid"),rows["sessionid"])
def load_session(profile):
 try:return keyring.get_password(SERVICE,_key(profile,"sessionid")) or ""
 except Exception:return ""
def load_session_cookies(profile):
 try:
  saved=keyring.get_password(SERVICE,_key(profile,"cookies")) or ""
  if saved:return tiktok_session_bundle.loads(saved)
 except Exception:pass
 legacy=load_session(profile);return tiktok_session_bundle.parse(legacy) if legacy else {}
def has_session(profile):return bool(load_session_cookies(profile))
def delete_session(profile):
 for field in ("sessionid","cookies"):
  try:keyring.delete_password(SERVICE,_key(profile,field))
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
def locator_attached(locator):
 try:return locator.count()>0
 except PlaywrightError:return False
def file_input_ready(page):
 try:return locator_attached(page.locator('input[type="file"]'))
 except PlaywrightError:return False
def _existing_auth(context):
 found={}
 try:
  for cookie in context.cookies(["https://www.tiktok.com"]):
   name=str(cookie.get("name") or "");value=str(cookie.get("value") or "")
   if name in SESSION_COOKIE_NAMES and value:found[name]=value
 except PlaywrightError:pass
 return found
def _remove_known_fabricated_alias(context,rows,existing):
 primary=rows.get("sessionid")
 if set(rows)=={"sessionid"} and primary and existing.get("sessionid_ss")==primary:
  try:context.clear_cookies(name="sessionid_ss")
  except (AttributeError,TypeError,PlaywrightError):pass
def bootstrap_session(context,profile,force=False):
 rows=load_session_cookies(profile)
 if not rows:return False
 existing=_existing_auth(context)
 if not force and all(existing.get(name)==value for name,value in rows.items()):return False
 _remove_known_fabricated_alias(context,rows,existing)
 cookies=[{"name":name,"value":value,"domain":".tiktok.com","path":"/","secure":True,"httpOnly":True,"sameSite":"Lax" if name=="sessionid" else "None"} for name,value in rows.items()]
 try:context.add_cookies(cookies)
 except PlaywrightError as exc:raise LoginError(f"{profile}: TikTok session çerezleri tarayıcıya yüklenemedi") from exc
 installed=_existing_auth(context);missing=[name for name,value in rows.items() if installed.get(name)!=value]
 if missing:raise LoginError(f"{profile}: Session çerezleri doğrulanamadı: {', '.join(missing)}")
 return True
def _page_context(page):
 try:return page.context
 except AttributeError:return None
def wait_for_upload_after_login(page,timeout_seconds=900,status=None,profile=""):
 deadline=time.monotonic()+timeout_seconds;repaired=False;last_navigation=0.0
 while time.monotonic()<deadline:
  if page.is_closed():raise LoginError("TikTok penceresi kapatıldı")
  if file_input_ready(page):
   if status:status("TikTok session doğrulandı; upload hazır")
   return
  url=page.url.lower();now=time.monotonic();on_login="/login" in url or _visible(page.locator('input[type="password"]'))
  if on_login:
   context=_page_context(page)
   if context is not None and has_session(profile) and not repaired:
    repaired=True;bootstrap_session(context,profile,force=True)
    if status:status(f"{profile}: Session ID yeniden yüklendi, upload açılıyor")
    try:page.goto(UPLOAD_URL,wait_until="domcontentloaded",timeout=90000)
    except PlaywrightTimeout:pass
    continue
   raise LoginError(f"{profile}: TikTok bu Session ID'yi reddetti; güncel sessionid veya Cookie bilgisini kaydedin")
  if "tiktokstudio/upload" not in url and now-last_navigation>4:
   try:page.goto(UPLOAD_URL,wait_until="domcontentloaded",timeout=90000)
   except PlaywrightTimeout:pass
   last_navigation=now;continue
  page.wait_for_timeout(750)
 raise LoginError("TikTok session/giriş doğrulaması tamamlanmadı")
def handle_copyright_publish_dialog(page,timeout_seconds=20.0):return copyright_dialog.handle(page,timeout_seconds)

def install(web_uploader:Any):
 """Install the core launch hook first; optional UI APIs may be absent."""
 if getattr(web_uploader,"_signaldesk_login_installed",False):
  preflight_hook.install(web_uploader);return
 original_launch=optional_callable(web_uploader,"launch_context")
 if original_launch is None:raise LoginError("Web uploader tarayıcı başlatma metodu bulunamadı")
 def launch(playwright,profile):
  context=original_launch(playwright,profile)
  try:bootstrap_session(context,profile,force=False)
  except Exception:
   try:context.close()
   except Exception:pass
   raise
  return context
 # Critical ordering: publish immediately, before touching optional methods.
 web_uploader.launch_context=launch;web_uploader.file_input_ready=file_input_ready;web_uploader._signaldesk_login_installed=True
 original_confirm=optional_callable(web_uploader,"confirm_publish_dialog")
 if original_confirm is not None:
  def confirm_for_every_profile(page):
   if handle_copyright_publish_dialog(page):return
   return original_confirm(page)
  web_uploader.confirm_publish_dialog=confirm_for_every_profile
 original_notice=optional_callable(web_uploader,"dismiss_pre_caption_notice")
 if original_notice is not None:
  def dismiss_notice(page,status=None,timeout_seconds=45,optional_after_seconds=8):
   tiktok_overlays.clear_new_account_overlays(page,status=status,timeout_seconds=12,quiet_seconds=1.2)
   result=original_notice(page,status=status,timeout_seconds=timeout_seconds,optional_after_seconds=optional_after_seconds)
   tiktok_overlays.clear_new_account_overlays(page,status=status,timeout_seconds=12,quiet_seconds=1.2);return result
  web_uploader.dismiss_pre_caption_notice=dismiss_notice
 original_fill=optional_callable(web_uploader,"fill_caption")
 if original_fill is not None:
  def fill_after_overlays(page,caption,timeout_seconds=180):
   tiktok_overlays.clear_new_account_overlays(page,timeout_seconds=20,quiet_seconds=1.5)
   try:return original_fill(page,caption,timeout_seconds=timeout_seconds)
   except (PlaywrightTimeout,PlaywrightError):
    tiktok_overlays.clear_new_account_overlays(page,timeout_seconds=20,quiet_seconds=1.5);return original_fill(page,caption,timeout_seconds=timeout_seconds)
  web_uploader.fill_caption=fill_after_overlays
 original_prepare=optional_callable(web_uploader,"prepare_upload")
 if original_prepare is not None and accepts_parameter(original_prepare,"status"):
  def prepare(request,*args,**kwargs):
   status=kwargs.get("status")
   if callable(status):status(f"{request.profile}: Session ID tarayıcıya navigasyondan önce yüklendi")
   return original_prepare(request,*args,**kwargs)
  web_uploader.prepare_upload=prepare
 preflight_hook.install(web_uploader)
