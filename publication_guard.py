from __future__ import annotations

import json,re,time
from datetime import datetime,timezone
from pathlib import Path
from platformdirs import user_data_dir
from playwright.sync_api import Error as PlaywrightError,TimeoutError as PlaywrightTimeout
DATA_ROOT=Path(user_data_dir("signaldesk-web-uploader","SignalDesk"))
PRIVATE_AUDIENCE=re.compile(r"^(?:only you|private|just me|yalnızca ben|yalnızca sen|sadece ben|özel)$",re.I)
HARD_BLOCK=re.compile(r"account (?:is )?(?:restricted|suspended|banned)|posting (?:is )?(?:restricted|unavailable)|you can.t post|not eligible for (?:the )?for you|ineligible for recommendation|hesab(?:ınız|ın) kısıtlı|hesap askıya alındı|paylaşım kısıtlandı|önerilere uygun değil|sizin için akışına uygun değil",re.I)
CHECK_PENDING=re.compile(r"copyright check.*(?:in progress|not finished|incomplete)|content check.*(?:in progress|not finished|incomplete)|telif hakkı kontrolü.*(?:sürüyor|tamamlanmadı|eksik)|içerik kontrolü.*(?:sürüyor|tamamlanmadı|eksik)",re.I)
POST_FAILURE=re.compile(r"something went wrong|try again|couldn.t post|failed to post|publish failed|unable to publish|bir şeyler yanlış gitti|tekrar dene|paylaş(?:ım|ma) başarısız|yayınla(?:ma|nma) başarısız|gönderilemedi",re.I)
POST_SUCCESS=re.compile(r"(?:your )?(?:video|post) (?:has been )?(?:published|posted|submitted)|(?:video|post) (?:published|posted|submitted) successfully|(?:video|gönderi) (?:yayınlandı|paylaşıldı|gönderildi)|yayınlama başarılı|paylaşım başarılı",re.I)
POST_REVIEW=re.compile(r"under review|being reviewed|not eligible for (?:the )?for you|ineligible for recommendation|inceleme altında|inceleniyor|önerilere uygun değil|sizin için akışına uygun değil",re.I)
CONTENT_DESTINATION=re.compile(r"/(?:tiktokstudio/(?:content|posts|manage)|creator-center/(?:content|posts)|manage/posts)(?:[/?#]|$)",re.I)
def _normalize(v):return re.sub(r"\s+"," ",v or "").strip()
def _body(page):
    try:return page.locator("body").inner_text(timeout=2000)
    except (PlaywrightTimeout,PlaywrightError):return ""
def _labels(page):
    loc=page.locator('[role="combobox"],[aria-haspopup="listbox"],[data-e2e*="privacy" i],[data-e2e*="visibility" i],[class*="privacy" i],[class*="visibility" i]');out=[]
    try:count=min(loc.count(),40)
    except PlaywrightError:return out
    for i in range(count):
        item=loc.nth(i)
        try:
            if item.is_visible(timeout=150):out.append(_normalize(item.get_attribute("aria-label") or item.inner_text(timeout=500) or ""))
        except (PlaywrightTimeout,PlaywrightError):pass
    return out
def assert_publishable(page,status=None):
    text=_body(page);blocked=HARD_BLOCK.search(text);pending=CHECK_PENDING.search(text)
    if blocked:raise RuntimeError(f"TikTok hesap/gönderi kısıtı: {_normalize(blocked.group(0))}")
    if pending:raise RuntimeError("İçerik/telif kontrolü tamamlanmadı")
    for label in _labels(page):
        if PRIVATE_AUDIENCE.fullmatch(label):raise RuntimeError(f"Hedef kitle {label}; dış izlenme alamaz")
    if status:status("Yayın öncesi görünürlük ve kısıt kontrolleri geçti")
def _editor(page):
    try:return page.locator('input[type="file"]').count()>0
    except PlaywrightError:return True
def _receipt(profile,page,evidence,health="ok"):
    folder=DATA_ROOT/"publish-receipts";folder.mkdir(parents=True,exist_ok=True);target=folder/datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f.json");temp=target.with_suffix(".tmp");temp.write_text(json.dumps({"profile":profile,"url":page.url,"evidence":evidence,"post_health":health,"verified_at":datetime.now(timezone.utc).isoformat()},ensure_ascii=False,indent=2),encoding="utf-8");temp.replace(target);return target
def wait_for_verified_publication(page,profile,status=None,timeout_seconds=180):
    deadline=time.monotonic()+timeout_seconds;started=time.monotonic()
    while time.monotonic()<deadline:
        if page.is_closed():raise RuntimeError("Yayın sonucu doğrulanmadan pencere kapatıldı")
        text=_body(page);failed=POST_FAILURE.search(text);review=POST_REVIEW.search(text)
        if failed:raise RuntimeError(f"TikTok yayın hatası: {_normalize(failed.group(0))}")
        if review:raise RuntimeError(f"Gönderi yayınlandı ancak erişim riski görüldü: {_normalize(review.group(0))}")
        for label in _labels(page):
            if PRIVATE_AUDIENCE.fullmatch(label):raise RuntimeError(f"Yayın sonrası hedef kitle {label}; dış izlenme alamaz")
        success=POST_SUCCESS.search(text)
        if success:
            receipt=_receipt(profile,page,_normalize(success.group(0)))
            if status:status(f"Yayın ve görünür kısıt kontrolü doğrulandı: {receipt}")
            return
        if time.monotonic()-started>=3 and CONTENT_DESTINATION.search(page.url) and not _editor(page):
            receipt=_receipt(profile,page,"content-page-navigation")
            if status:status(f"İçerik sayfası ve yayın sonrası durum doğrulandı: {receipt}")
            return
        page.wait_for_timeout(1000)
    raise RuntimeError("Üç dakika içinde kesin yayın kanıtı alınamadı")
