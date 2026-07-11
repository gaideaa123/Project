from __future__ import annotations

"""Strict post-click verification for the visible TikTok Studio uploader.

Upload completion is not publication completion. This module deliberately ignores
pre-existing "upload complete" copy and accepts only post-publication UI or a
navigation away from the upload editor to a known content-management surface.
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

PUBLISH_FAILURE = re.compile(
    r"something went wrong|try again|couldn.t post|failed to post|post failed|"
    r"publish failed|unable to publish|bir şeyler yanlış gitti|tekrar dene|"
    r"paylaş(?:ım|ma) başarısız|yayınla(?:ma|nma) başarısız|gönderilemedi|"
    r"video is under review|video is being reviewed|inceleme altında",
    re.I,
)

# Deliberately excludes "upload complete/completed/yüklendi". Those strings are
# visible before Post is clicked and caused the old false-success path.
PUBLISH_SUCCESS = re.compile(
    r"^(?:your (?:video|post) (?:has been )?(?:published|posted|submitted)|"
    r"(?:video|post) (?:published|posted|submitted) successfully|"
    r"(?:video|gönderi) (?:yayınlandı|paylaşıldı|gönderildi)|"
    r"yayınlama başarılı|paylaşım başarılı)[.!]?$",
    re.I,
)

PRIVATE_AUDIENCE = re.compile(
    r"^(?:only you|private|just me|yalnızca sen|yalnızca ben|sadece ben|özel)$",
    re.I,
)

CONTENT_URL = re.compile(
    r"/(?:tiktokstudio/(?:content|posts|manage)|creator-center/(?:content|posts)|manage/posts)(?:[/?#]|$)",
    re.I,
)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _visible_text(locator, limit: int = 40) -> list[str]:
    values: list[str] = []
    try:
        count = min(locator.count(), limit)
    except PlaywrightError:
        return values
    for index in range(count):
        item = locator.nth(index)
        try:
            if not item.is_visible(timeout=150):
                continue
            text = _normalize(item.inner_text(timeout=500) or item.get_attribute("aria-label") or "")
            if text:
                values.append(text)
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return values


def assert_non_private_audience(page: Page, status: Callable[[str], None] | None = None) -> None:
    """Fail before clicking Post when TikTok visibly shows a private audience."""
    controls = page.locator(
        '[role="combobox"], [aria-haspopup="listbox"], [data-e2e*="privacy" i], '
        '[data-e2e*="visibility" i], [class*="privacy" i], [class*="visibility" i]'
    )
    selected = _visible_text(controls)
    private = next((text for text in selected if PRIVATE_AUDIENCE.fullmatch(text)), "")
    if private:
        raise RuntimeError(
            f"TikTok görünürlüğü '{private}' durumda. Bu yayın dış izlenme alamaz; "
            "tarayıcıda görünürlüğü uygun kitleye getirip yeniden deneyin."
        )
    if status:
        status("TikTok görünürlük kontrolü geçti; yayın sonrası kesin kanıt beklenecek")


def _success_notice(page: Page) -> str:
    candidates = page.locator(
        '[role="alert"], [role="status"], [aria-live="assertive"], '
        '[aria-live="polite"], [data-e2e*="toast" i], [class*="toast" i]'
    )
    for text in _visible_text(candidates):
        if PUBLISH_FAILURE.search(text):
            raise RuntimeError(f"TikTok yayını reddetti: {text[:300]}")
        if PUBLISH_SUCCESS.fullmatch(text):
            return text
    return ""


def _body_failure(page: Page) -> str:
    try:
        text = page.locator("body").inner_text(timeout=1500)
    except (PlaywrightTimeout, PlaywrightError):
        return ""
    match = PUBLISH_FAILURE.search(text)
    return _normalize(match.group(0)) if match else ""


def _upload_editor_present(page: Page) -> bool:
    try:
        if page.locator('input[type="file"]').count():
            return True
        buttons = page.get_by_role(
            "button", name=re.compile(r"^(?:post|publish|share|yayınla|paylaş)$", re.I)
        )
        return bool(buttons.count() and buttons.first.is_visible(timeout=200))
    except (PlaywrightTimeout, PlaywrightError):
        return True


def write_receipt(profile: str, url: str, evidence: str) -> Path:
    folder = DATA_ROOT / "publish-receipts"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f.json")
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "profile": profile,
        "url": url,
        "evidence": evidence,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def wait_for_publish_result(
    page: Page,
    timeout_seconds: int = 180,
    status: Callable[[str], None] | None = None,
    profile: str = "",
) -> None:
    """Require publication evidence; never treat upload completion as success."""
    deadline = time.monotonic() + timeout_seconds
    started = time.monotonic()
    while time.monotonic() < deadline:
        if page.is_closed():
            raise RuntimeError("TikTok penceresi yayın sonucu doğrulanmadan kapatıldı")

        failure = _body_failure(page)
        if failure:
            raise RuntimeError(f"TikTok yayın hatası gösterdi: {failure}")

        notice = _success_notice(page)
        if notice:
            receipt = write_receipt(profile, page.url, f"success-notice: {notice}")
            if status:
                status(f"TikTok yayını kesin olarak doğrulandı; kayıt: {receipt}")
            return

        url = page.url
        # Allow the UI a few seconds to settle, then accept only a known content
        # destination with the upload editor gone. Arbitrary URL changes are not success.
        if time.monotonic() - started >= 3 and CONTENT_URL.search(url) and not _upload_editor_present(page):
            receipt = write_receipt(profile, url, "content-page-navigation")
            if status:
                status(f"TikTok içerik ekranına geçti; yayın doğrulandı: {receipt}")
            return

        if status and int(time.monotonic() - started) % 15 == 0:
            status("Yayınla tıklandı; TikTok'un gerçek yayın sonucunu bekliyorum")
        page.wait_for_timeout(1000)

    raise RuntimeError(
        "TikTok 3 dakika içinde kesin yayın kanıtı vermedi. İşlem başarılı sayılmadı; "
        "tarayıcıdaki hata, hesap durumu ve gönderi görünürlüğünü kontrol edin."
    )
