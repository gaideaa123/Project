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

SERVICE = "signaldesk-tiktok-web-login"
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=creator_center"
SESSION_COOKIE_NAMES = tiktok_session_bundle.AUTH_COOKIE_NAMES

class LoginError(RuntimeError): pass

def _key(profile: str, field: str) -> str:
 clean=re.sub(r"[^a-zA-Z0-9_.-]+","-",profile.strip()).strip("-.")[:80]
 if not clean: raise LoginError("Profil adı geçersiz")
 return f"{clean}:{field}"

def _session_value(raw: str) -> str:
 try:return tiktok_session_bundle.parse(raw)["sessionid"]
 except ValueError as exc:raise LoginError(str(exc)) from exc

def save_session(profile: str,value: str)->None:
 try:rows=tiktok_session_bundle.parse(value)
 except ValueError as exc:raise LoginError(str(exc)) from exc
 keyring.set_password(SERVICE,_key(profile,"cookies"),tiktok_session_bundle.dumps(rows))
 keyring.set_password(SERVICE,_key(profile,"sessionid"),rows["sessionid"])

def load_session(profile: str)->str:
 try:return keyring.get_password(SERVICE,_key(profile,"sessionid")) or ""
 except Exception:return ""

def load_session_cookies(profile: str)->dict[str,str]:
 try:
  saved=keyring.get_password(SERVICE,_key(profile,"cookies")) or ""
  if saved:return tiktok_session_bundle.loads(saved)
 except Exception:pass
 legacy=load_session(profile)
 return tiktok_session_bundle.parse(legacy) if legacy else {}

def has_session(profile: str)->bool:return bool(load_session_cookies(profile))
def delete_session(profile: str)->None:
 for field in ("sessionid","cookies"):
  try:keyring.delete_password(SERVICE,_key(profile,field))
  except Exception:pass

def save_credentials(profile: str,identity: str,password: str)->None:
 if not identity.strip() or not password:raise LoginError("Kullanıcı ve parola birlikte girilmeli")
 keyring.set_password(SERVICE,_key(profile,"identity"),identity.strip());keyring.set_password(SERVICE,_key(profile,"password"),password)
def load_credentials(profile: str)->tuple[str,str]:
 try:return (keyring.get_password(SERVICE,_key(profile,"identity")) or "",keyring.get_password(SERVICE,_key(profile,"password")) or "")
 except Exception:return "",""
def has_credentials(profile: str)->bool:return all(load_credentials(profile))

def _visible(locator,timeout=400):
 try:return bool(locator.count() and locator.first.is_visible(timeout=timeout))
 except (PlaywrightTimeout,PlaywrightError):return False
def locator_attached(locator)->bool:
 try:return locator.count()>0
 except PlaywrightError:return False
def file_input_ready(page)->bool:
 try:return locator_attached(page.locator('input[type="file"]'))
 except PlaywrightError:return False

def _existing_auth(context)->dict[str,str]:
 found={}
 try:
  for cookie in context.cookies(["https://www.tiktok.com"]):
   name=str(cookie.get("name") or "");value=str(cookie.get("value") or "")
   if name in SESSION_COOKIE_NAMES and value:found[name]=value
 except PlaywrightError:pass
 return found

def _remove_known_fabricated_alias(context,rows:dict[str,str],existing:dict[str,str])->None:
 """Remove only the alias created by the previous regression, nothing else."""
 primary=rows.get("sessionid")
 if set(rows)=={"sessionid"} and primary and existing.get("sessionid_ss")==primary:
  try:context.clear_cookies(name="sessionid_ss")
  except (AttributeError,TypeError,PlaywrightError):pass

def bootstrap_session(context,profile: str,force: bool=False)->bool:
 """Add supplied cookies without deleting TikTok's device/CSRF state."""
 rows=load_session_cookies(profile)
 if not rows:return False
 existing=_existing_auth(context)
 if not force and all(existing.get(name)==value for name,value in rows.items()):return False
 _remove_known_fabricated_alias(context,rows,existing)
 cookies=[{"name":name,"value":value,"domain":".tiktok.com","path":"/","secure":True,"httpOnly":True,"sameSite":"Lax" if name=="sessionid" else "None"} for name,value in rows.items()]
 try:context.add_cookies(cookies)
 except PlaywrightError as exc:raise LoginError(f"{profile}: TikTok session çerezleri tarayıcıya yüklenemedi") from exc
 installed=_existing_auth(context)
 missing=[name for name,value in rows.items() if installed.get(name)!=value]
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
    if status:status(f"{profile}: Session ID cihaz çerezleri korunarak yeniden yüklendi")
    try:
     page.goto("https://www.tiktok.com/",wait_until="domcontentloaded",timeout=90000)
     page.wait_for_timeout(1000)
     page.goto(UPLOAD_URL,wait_until="domcontentloaded",timeout=90000)
    except PlaywrightTimeout:pass
    continue
   raise LoginError(f"{profile}: TikTok bu Session ID'yi reddetti. Session süresi dolmuş veya seçili proxy/IP ile eşleşmiyor; güncel sessionid kaydedin.")
  if "tiktokstudio/upload" not in url and now-last_navigation>4:
   try:page.goto(UPLOAD_URL,wait_until="domcontentloaded",timeout=90000)
   except PlaywrightTimeout:pass
   last_navigation=now;continue
  page.wait_for_timeout(750)
 raise LoginError("TikTok session/giriş doğrulaması tamamlanmadı")

def handle_copyright_publish_dialog(page,timeout_seconds=20.0)->bool:return copyright_dialog.handle(page,timeout_seconds)

def install(web_uploader: Any):
 if getattr(web_uploader,"_signaldesk_login_installed",False):preflight_hook.install(web_uploader);return
 original_launch=web_uploader.launch_context;original_prepare=web_uploader.prepare_upload
 original_confirm=web_uploader.confirm_publish_dialog;original_notice=web_uploader.dismiss_pre_caption_notice;original_fill=web_uploader.fill_caption
 web_uploader.file_input_ready=file_input_ready
 def launch(playwright,profile):
  context=original_launch(playwright,profile)
  try:bootstrap_session(context,profile,force=False)
  except Exception:
   try:context.close()
   except Exception:pass
   raise
  return context
 def confirm_for_every_profile(page):
  if handle_copyright_publish_dialog(page):return
  original_confirm(page)
 def dismiss_pre_caption_notice(page,status=None,timeout_seconds=45,optional_after_seconds=8):
  tiktok_overlays.clear_new_account_overlays(page,status=status,timeout_seconds=12,quiet_seconds=1.2)
  result=original_notice(page,status=status,timeout_seconds=timeout_seconds,optional_after_seconds=optional_after_seconds)
  tiktok_overlays.clear_new_account_overlays(page,status=status,timeout_seconds=12,quiet_seconds=1.2);return result
 def fill_caption_after_overlays(page,caption,timeout_seconds=180):
  tiktok_overlays.clear_new_account_overlays(page,timeout_seconds=20,quiet_seconds=1.5)
  try:return original_fill(page,caption,timeout_seconds=timeout_seconds)
  except (PlaywrightTimeout,PlaywrightError):
   tiktok_overlays.clear_new_account_overlays(page,timeout_seconds=20,quiet_seconds=1.5);return original_fill(page,caption,timeout_seconds=timeout_seconds)
 def prepare(request,publish=False,approval=None,status=None):
  original_wait=web_uploader.wait_for_upload_after_login;previous_confirm=web_uploader.confirm_publish_dialog
  def waiter(page,timeout_seconds=900,status=None):
   result=wait_for_upload_after_login(page,timeout_seconds,status,request.profile)
   tiktok_overlays.clear_new_account_overlays(page,status=status,timeout_seconds=20,quiet_seconds=1.5);return result
  web_uploader.wait_for_upload_after_login=waiter;web_uploader.confirm_publish_dialog=confirm_for_every_profile
  if status:status(f"{request.profile}: kalıcı cihaz çerezleri korunarak Session ID hazırlanıyor")
  try:return original_prepare(request,publish=publish,approval=approval,status=status)
  finally:web_uploader.wait_for_upload_after_login=original_wait;web_uploader.confirm_publish_dialog=previous_confirm
 web_uploader.launch_context=launch;web_uploader.confirm_publish_dialog=confirm_for_every_profile
 web_uploader.dismiss_pre_caption_notice=dismiss_pre_caption_notice;web_uploader.fill_caption=fill_caption_after_overlays
 web_uploader.prepare_upload=prepare;web_uploader._signaldesk_login_installed=True;preflight_hook.install(web_uploader)
