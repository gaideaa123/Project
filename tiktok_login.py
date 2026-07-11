from __future__ import annotations

"""Profile-scoped TikTok session and onboarding integration."""

import inspect
import re
from typing import Any

import keyring
from playwright.sync_api import Error as PlaywrightError

import tiktok_overlays

SERVICE = "signaldesk-tiktok-web-login"
SESSION_COOKIE_NAMES = ("sessionid", "sessionid_ss")

class LoginError(RuntimeError):
 pass

def _key(profile: str, field: str) -> str:
 clean = re.sub(r"[^a-zA-Z0-9_.-]+", "-", profile.strip()).strip("-.")[:80]
 if not clean: raise LoginError("Profil adı geçersiz")
 return f"{clean}:{field}"

def _session_value(raw: str) -> str:
 value = raw.strip(); match = re.search(r"(?:^|;\s*)sessionid(?:_ss)?=([^;\s]+)", value, re.I)
 value = match.group(1) if match else value
 if not value or len(value) < 16 or re.search(r"\s", value): raise LoginError("Geçerli sessionid girin")
 return value

def save_session(profile: str, value: str) -> None: keyring.set_password(SERVICE, _key(profile, "sessionid"), _session_value(value))
def load_session(profile: str) -> str:
 try: return keyring.get_password(SERVICE, _key(profile, "sessionid")) or ""
 except Exception: return ""
def has_session(profile: str) -> bool: return bool(load_session(profile))
def delete_session(profile: str) -> None:
 try: keyring.delete_password(SERVICE, _key(profile, "sessionid"))
 except Exception: pass
def save_credentials(profile: str, identity: str, password: str) -> None:
 if not identity.strip() or not password: raise LoginError("Kullanıcı ve parola birlikte girilmeli")
 keyring.set_password(SERVICE, _key(profile, "identity"), identity.strip()); keyring.set_password(SERVICE, _key(profile, "password"), password)
def load_credentials(profile: str) -> tuple[str, str]:
 try: return (keyring.get_password(SERVICE, _key(profile, "identity")) or "", keyring.get_password(SERVICE, _key(profile, "password")) or "")
 except Exception: return "", ""
def has_credentials(profile: str) -> bool: return all(load_credentials(profile))

def _existing_session(context) -> dict[str, str]:
 found: dict[str, str] = {}
 try:
  for cookie in context.cookies(["https://www.tiktok.com"]):
   name = str(cookie.get("name") or ""); value = str(cookie.get("value") or "")
   if name in SESSION_COOKIE_NAMES and value: found[name] = value
 except PlaywrightError: pass
 return found

def _clear_session_cookies(context) -> None:
 for name in SESSION_COOKIE_NAMES:
  try: context.clear_cookies(name=name)
  except (AttributeError, TypeError): return
  except PlaywrightError as exc: raise LoginError(f"Eski TikTok {name} çerezi temizlenemedi") from exc

def bootstrap_session(context, profile: str, force: bool = True) -> bool:
 session_id = load_session(profile)
 if not session_id: return False
 existing = _existing_session(context)
 if not force and any(value == session_id for value in existing.values()): return False
 _clear_session_cookies(context)
 cookies = [{"name": name, "value": session_id, "domain": ".tiktok.com", "path": "/", "secure": True, "httpOnly": True, "sameSite": "None"} for name in SESSION_COOKIE_NAMES]
 try: context.add_cookies(cookies)
 except PlaywrightError as exc: raise LoginError(f"{profile}: Session ID tarayıcıya yüklenemedi") from exc
 installed = _existing_session(context)
 if installed and not all(installed.get(name) == session_id for name in SESSION_COOKIE_NAMES): raise LoginError(f"{profile}: Session ID tarayıcıda doğrulanamadı")
 return True

def _wrap_overlay_stage(web_uploader: Any, name: str, before: bool, after: bool) -> None:
 original = getattr(web_uploader, name, None)
 if not callable(original) or getattr(original, "_content_check_wrapped", False): return
 if name == "wait_for_login":
  def wrapped(page, timeout_seconds=600):
   result = original(page, timeout_seconds)
   tiktok_overlays.clear_new_account_overlays(page, timeout_seconds=25)
   return result
 elif name == "upload_file":
  def wrapped(page, video):
   if before: tiktok_overlays.clear_new_account_overlays(page, timeout_seconds=8, minimum_scan_seconds=2)
   result = original(page, video)
   if after: tiktok_overlays.clear_new_account_overlays(page, timeout_seconds=25)
   return result
 elif name == "fill_caption":
  def wrapped(page, caption, timeout_seconds=180):
   if before: tiktok_overlays.clear_new_account_overlays(page, timeout_seconds=25)
   return original(page, caption, timeout_seconds)
 else:
  return
 wrapped._content_check_wrapped = True
 setattr(web_uploader, name, wrapped)

def install(web_uploader: Any) -> None:
 if getattr(web_uploader, "_signaldesk_login_installed", False): return
 original_launch = getattr(web_uploader, "launch_context", None)
 if not callable(original_launch): raise LoginError("Web uploader tarayıcı başlatma metodu bulunamadı")
 def launch(playwright, profile):
  context = original_launch(playwright, profile)
  try: bootstrap_session(context, profile, force=True)
  except Exception:
   try: context.close()
   except Exception: pass
   raise
  return context
 web_uploader.launch_context = launch
 _wrap_overlay_stage(web_uploader, "wait_for_login", False, True)
 _wrap_overlay_stage(web_uploader, "upload_file", True, True)
 _wrap_overlay_stage(web_uploader, "fill_caption", True, False)
 web_uploader._signaldesk_login_installed = True
 original_prepare = getattr(web_uploader, "prepare_upload", None)
 if callable(original_prepare) and "status" in inspect.signature(original_prepare).parameters:
  def prepare(request, *args, **kwargs):
   status = kwargs.get("status")
   if callable(status): status(f"{request.profile}: Session ID ve otomatik içerik kontrolleri hazırlanıyor")
   return original_prepare(request, *args, **kwargs)
  web_uploader.prepare_upload = prepare
