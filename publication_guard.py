from __future__ import annotations

"""Conservative TikTok Studio publication gates.

These checks do not hide automation or bypass platform controls. They prevent the
application from auto-publishing when the visible page already shows conditions
commonly associated with zero outside reach: private audience, account/posting
restrictions, incomplete checks, or an unverified publication result.
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from platformdirs import user_data_dir
from playwright.sync_api import Error as PlaywrightError, Page, TimeoutError as PlaywrightTimeout

DATA_ROOT = Path(user_data_dir("signaldesk-web-uploader", "SignalDesk"))

PRIVATE_AUDIENCE = re.compile(
    r"^(?:only you|private|just me|yalnızca ben|yalnızca sen|sadece ben|özel)$", re.I
)
HARD_BLOCK = re.compile(
    r"account (?:is )?(?:restricted|suspended|banned)|posting (?:is )?(?:restricted|unavailable)|"
    r"you can.t post|not eligible for (?:the )?for you|ineligible for recommendation|"
    r"hesab(?:ınız|ın) kısıtlı|hesap askıya alındı|paylaşım kısıtlandı|"
    r"gönderi oluşturamazsınız|önerilere uygun değil|sizin için akışına uygun değil",
    re.I,
)
CHECK_PENDING = re.compile(
    r"copyright check.*(?:in progress|not finished|incomplete)|"
    r"content check.*(?:in progress|not finished|incomplete)|"
    r"telif hakkı kontrolü.*(?:sürüyor|tamamlanmadı|eksik)|"
    r"içerik kontrolü.*(?:sürüyor|tamamlanmadı|eksik)",
    re.I,
)
POST_FAILURE = re.compile(
    r"something went wrong|try again|couldn.t post|failed to post|publish failed|"
    r"unable to publish|bir şeyler yanlış gitti|tekrar dene|"
    r"paylaş(?:ım|ma) başarısız|yayınla(?:ma|nma) başarısız|gönderilemedi",
    re.I,
)
POST_SUCCESS = re.compile(
    r"(?:your )?(?:video|post) (?:has been )?(?:published|posted|submitted)|"
    r"(?:video|post) (?:published|posted|submitted) successfully|"
    r"(?:video|gönderi) (?:yayınlandı|paylaşıldı|gönderildi)|"
    r"yayınlama başarılı|paylaşım başarılı",
    re.I,
)
CONTENT_DESTINATION = re.compile(
    r"/(?:tiktokstudio/(?:content|posts|manage)|creator-center/(?:content|posts)|manage/posts)(?:[/?#]|$)",
    re.I,
)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _body_text(page: Page) -> str:
    try:
        return page.locator("body").inner_text(timeout=2000)
    except (PlaywrightTimeout, PlaywrightError):
        return ""


def _visible_labels(page: Page) -> list[str]:
    locator = page.locator(
        '[role="combobox"], [aria-haspopup="listbox"], [data-e2e*="privacy" i], '
        '[data-e2e*="visibility" i], [class*="privacy" i], [class*="visibility" i]'
    )
    labels: list[str] = []
    try:
        count = min(locator.count(), 40)
    except PlaywrightError:
        return labels
    for index in range(count):
        item = locator.nth(index)
        try:
            if not item.is_visible(timeout=150):
                continue
            value = _normalize(
                item.get_attribute("aria-label") or item.inner_text(timeout=500) or ""
            )
            if value:
                labels.append(value)
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return labels


def assert_publishable(page: Page, status: Callable[[str], None] | None = None) -> None:
    """Fail closed on visible private/restricted/pending states before Post."""
    text = _body_text(page)
    blocked = HARD_BLOCK.search(text)
    if blocked:
        raise RuntimeError(
            f"TikTok hesap/gönderi kısıtı gösteriyor: {_normalize(blocked.group(0))}. "
            "Otomatik yayın durduruldu; Account Status ekranını kontrol edin."
        )
    pending = CHECK_PENDING.search(text)
    if pending:
        raise RuntimeError(
            "TikTok içerik veya telif kontrolünü henüz tamamlamadı. Kontrol bitmeden "
            "yayınlamak sıfır erişim/inceleme riski taşır; işlem durduruldu."
        )
    for label in _visible_labels(page):
        if PRIVATE_AUDIENCE.fullmatch(label):
            raise RuntimeError(
                f"TikTok hedef kitlesi '{label}' görünüyor. Bu gönderi dış izlenme alamaz; "
                "profilin görünürlük ayarını düzeltip yeniden deneyin."
            )
    if status:
        status("Yayın öncesi görünürlük, hesap kısıtı ve içerik kontrol kapıları geçti")


def _upload_editor_present(page: Page) -> bool:
    try:
        if page.locator('input[type="file"]').count():
            return True
        button = page.get_by_role(
            "button", name=re.compile(r"^(?:post|publish|share|yayınla|paylaş)$", re.I)
        )
        return bool(button.count() and button.first.is_visible(timeout=200))
    except (PlaywrightTimeout, PlaywrightError):
        return True


def _write_receipt(profile: str, page: Page, evidence: str) -> Path:
    folder = DATA_ROOT / "publish-receipts"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f.json")
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "profile": profile,
        "url": page.url,
        "evidence": evidence,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def wait_for_verified_publication(
    page: Page,
    profile: str,
    status: Callable[[str], None] | None = None,
    timeout_seconds: int = 180,
) -> None:
    """Accept only post-publication evidence, never pre-existing upload text."""
    deadline = time.monotonic() + timeout_seconds
    started = time.monotonic()
    while time.monotonic() < deadline:
        if page.is_closed():
            raise RuntimeError("TikTok penceresi yayın sonucu doğrulanmadan kapatıldı")
        text = _body_text(page)
        failed = POST_FAILURE.search(text)
        if failed:
            raise RuntimeError(f"TikTok yayın hatası gösterdi: {_normalize(failed.group(0))}")
        success = POST_SUCCESS.search(text)
        if success:
            receipt = _write_receipt(profile, page, _normalize(success.group(0)))
            if status:
                status(f"TikTok yayını doğrulandı; yerel kayıt: {receipt}")
            return
        if (time.monotonic() - started >= 3 and CONTENT_DESTINATION.search(page.url)
                and not _upload_editor_present(page)):
            receipt = _write_receipt(profile, page, "content-page-navigation")
            if status:
                status(f"TikTok içerik ekranına geçti; yayın doğrulandı: {receipt}")
            return
        page.wait_for_timeout(1000)
    raise RuntimeError(
        "TikTok üç dakika içinde kesin yayın kanıtı vermedi. 'Upload complete' yayın "
        "başarısı sayılmadı; hesap durumu ve gönderi görünürlüğünü kontrol edin."
    )
