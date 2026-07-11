from __future__ import annotations

"""Automatic publish after completed checks, with bounded visible upload retries."""

import re
import time
from typing import Any,Callable
from playwright.sync_api import Error as PlaywrightError,TimeoutError as PlaywrightTimeout,sync_playwright
import publication_guard,upload_state

Status=Callable[[str],None]
PUBLISH_BUTTON=re.compile(r"^(paylaş|yayınla|gönder|post|publish|share)$",re.I)
CHECK_PENDING=re.compile(r"(?:içerik|telif|müzik).{0,35}(?:kontrol ediliyor|inceleniyor|sürüyor|bekleniyor|tamamlanmadı)|(?:content|copyright|music).{0,35}(?:checking|in progress|processing|pending|not finished)",re.I)
UPLOAD_PENDING=re.compile(r"(?:video\s*)?(?:yükleniyor|işleniyor|hazırlanıyor)\s*\d{0,3}\s*%?|(?:uploading|processing)\s*(?:video)?\s*\d{0,3}\s*%?",re.I)
ADVISORY=re.compile(r"özgün olmayan, düşük kaliteli ve qr kodlu içerik|özgün olmayan ve düşük kaliteli içerik|unoriginal, low-quality|qr code content|not eligible for recommendation",re.I)
MAX_UPLOAD_RETRIES=3

def _status(callback,message):
 if callback:callback(message)
def _body(page):
 try:return page.locator("body").inner_text(timeout=1800)
 except (PlaywrightTimeout,PlaywrightError):return ""
def _first_publish(page):
 for locator in [page.get_by_role("button",name=PUBLISH_BUTTON),page.locator('button[data-e2e*="post" i]'),page.locator('button[data-e2e*="publish" i]')]:
  try:
   item=locator.first
   if item.is_visible(timeout=350):return item
  except (PlaywrightTimeout,PlaywrightError):continue
 return None
def _progress_busy(page):
 bars=page.locator('[role="progressbar"]')
 try:count=min(bars.count(),12)
 except PlaywrightError:return True
 for index in range(count):
  bar=bars.nth(index)
  try:
   if not bar.is_visible(timeout=100):continue
   value=bar.get_attribute("aria-valuenow")
   if value is None or float(value)<100:return True
  except (PlaywrightError,ValueError):return True
 return False

def wait_for_checks_complete(page,status:Status|None=None,timeout_seconds:int=900):
 deadline=time.monotonic()+timeout_seconds;stable=0;last_notice=0.0;failure_key="";failure_hits=0;retries=0;retry_quiet_until=0.0
 while time.monotonic()<deadline:
  if page.is_closed():raise RuntimeError("TikTok penceresi içerik kontrolü tamamlanmadan kapatıldı")
  now=time.monotonic();text=_body(page)
  if ADVISORY.search(text):raise RuntimeError("TikTok içeriği özgün olmayan/düşük kaliteli/QR kodlu olarak sınıflandırdı. 'Yine de paylaş' seçilmedi; videoyu yeniden üretin.")
  visible_failure=upload_state.visible_upload_failure(page)
  if visible_failure and now>=retry_quiet_until:
   key=visible_failure.text.casefold();failure_hits=failure_hits+1 if key==failure_key else 1;failure_key=key
   if failure_hits>=3:
    if retries<MAX_UPLOAD_RETRIES and upload_state.click_retry(page,visible_failure):
     retries+=1;failure_hits=0;failure_key="";stable=0;retry_quiet_until=now+5
     _status(status,f"TikTok yüklemesi başarısız oldu; Tekrar dene tıklandı ({retries}/{MAX_UPLOAD_RETRIES})")
     page.wait_for_timeout(1500);continue
    selected=upload_state.selected_file(page);detail=f" Seçili dosya: {selected[0]} ({selected[1]} bayt)." if selected else ""
    reason="Tekrar dene düğmesi bulunamadı" if retries<MAX_UPLOAD_RETRIES else f"{MAX_UPLOAD_RETRIES} yeniden deneme başarısız oldu"
    raise RuntimeError(f"TikTok görünür yükleme hatası gösteriyor: {visible_failure.text}. {reason}.{detail}")
  elif not visible_failure:
   failure_key="";failure_hits=0
  pending=bool(CHECK_PENDING.search(text) or UPLOAD_PENDING.search(text) or _progress_busy(page))
  button=_first_publish(page);enabled=False
  if button is not None:
   try:enabled=button.is_enabled()
   except PlaywrightError:enabled=False
  if enabled and not pending and not visible_failure:
   stable+=1
   if stable>=3:_status(status,"Video yüklendi, içerik kontrolleri tamamlandı; Paylaş hazır");return button
  else:stable=0
  if now-last_notice>=8:_status(status,"Video yükleme ve içerik kontrolünün tamamlanması bekleniyor");last_notice=now
  page.wait_for_timeout(1000)
 raise RuntimeError("TikTok içerik kontrolünü 15 dakikada tamamlamadı")

def _click(locator,page):
 try:locator.scroll_into_view_if_needed(timeout=2500)
 except (AttributeError,PlaywrightError):pass
 try:locator.click(timeout=5000);return True
 except PlaywrightError:
  try:locator.click(timeout=5000,force=True);return True
  except PlaywrightError:return False

def install(web_uploader:Any)->None:
 if getattr(web_uploader,"_automatic_publish_installed",False):return
 required=("launch_context","wait_for_login","upload_file","fill_caption","goto_upload")
 if not all(callable(getattr(web_uploader,name,None)) for name in required):raise RuntimeError("Web uploader otomatik yayın için gerekli metotları sunmuyor")
 request_type=web_uploader.UploadRequest
 def prepare_upload(request,publish=False,approval=None,status=None):
  request.validate()
  with sync_playwright() as playwright:
   context=web_uploader.launch_context(playwright,request.profile);page=context.pages[0] if context.pages else context.new_page()
   try:
    _status(status,f"{request.profile}: TikTok Studio açılıyor");web_uploader.goto_upload(page);web_uploader.wait_for_login(page);web_uploader.upload_file(page,request.video)
    selected=upload_state.selected_file(page)
    if selected and selected[1]<=0:raise RuntimeError("Tarayıcıya seçilen video dosyası boş")
    web_uploader.fill_caption(page,request.caption);button=wait_for_checks_complete(page,status=status);page.bring_to_front()
    if not publish:
     while context.pages:page.wait_for_timeout(1000)
     return
    publication_guard.assert_publishable(page,status);_status(status,f"{request.profile}: içerik kontrolü bitti, Paylaş tıklanıyor")
    if not _click(button,page):raise RuntimeError("TikTok Paylaş düğmesine tıklanamadı")
    publication_guard.wait_for_verified_publication(page,request.profile,status=status,timeout_seconds=180)
   except Exception as exc:
    folder=web_uploader.save_diagnostics(page,request.profile,exc);raise web_uploader.UploadError(f"{exc}\nTanı dosyaları: {folder}") from exc
   finally:context.close()
 web_uploader.prepare_upload=prepare_upload;web_uploader.UploadRequest=request_type;web_uploader._automatic_publish_installed=True
