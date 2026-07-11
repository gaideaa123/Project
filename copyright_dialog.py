from __future__ import annotations

"""Fail closed when TikTok reports an incomplete copyright check.

Publishing through the warning can leave a post pending review or ineligible for
recommendation. The safe behavior is to cancel that publish attempt, preserve a
clear diagnostic, and let the operator retry only after TikTok finishes checking.
"""

import re
import time

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

COPYRIGHT_WARNING = re.compile(
    r"paylaşmaya devam edilsin mi|"
    r"telif hakkı kontrolü eksik|"
    r"kontrol tamamlanmadan önce paylaşmaya devam etmek ister misiniz|"
    r"copyright check.*(?:incomplete|not finished|has not finished|in progress)|"
    r"continue (?:sharing|posting|publishing).*(?:copyright|check)",
    re.I,
)
# Kept as a recognition constant for diagnostics and backward-compatible tests.
# The handler intentionally never clicks this action.
IMMEDIATE_SHARE = re.compile(
    r"^(hemen paylaş|hemen yayınla|share now|publish now|post now)$",
    re.I,
)
CANCEL = re.compile(r"^(iptal|cancel)$", re.I)
MODAL_SELECTORS = (
    '[role="dialog"]',
    '[aria-modal="true"]',
    '[class*="modal" i]',
    '[class*="dialog" i]',
)


class CopyrightDialogError(RuntimeError):
    pass


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _visible(locator, timeout: int = 250) -> bool:
    try:
        return bool(locator.count() and locator.first.is_visible(timeout=timeout))
    except (PlaywrightTimeout, PlaywrightError):
        return False


def _click_exact_cancel(container) -> bool:
    by_role = container.get_by_role("button", name=CANCEL)
    if _visible(by_role, 400):
        by_role.first.click(timeout=5000)
        return True

    by_text = container.get_by_text(CANCEL, exact=True)
    if _visible(by_text, 400):
        target = by_text.first
        try:
            target.click(timeout=5000)
        except PlaywrightError:
            target.locator(
                "xpath=ancestor::*[self::button or @role='button'][1]"
            ).click(timeout=5000)
        return True

    candidates = container.locator("button, [role='button']")
    try:
        count = min(candidates.count(), 30)
    except PlaywrightError:
        count = 0
    for index in range(count):
        candidate = candidates.nth(index)
        try:
            label = normalize(
                candidate.get_attribute("aria-label")
                or candidate.inner_text(timeout=500)
            )
            if CANCEL.fullmatch(label) and candidate.is_visible(timeout=300):
                candidate.click(timeout=5000)
                return True
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return False


def _verified_containers(page):
    """Yield only visible modal containers containing the incomplete-check warning."""
    seen: set[str] = set()
    for selector in MODAL_SELECTORS:
        locators = page.locator(selector)
        try:
            count = min(locators.count(), 20)
        except PlaywrightError:
            count = 0
        for index in range(count):
            container = locators.nth(index)
            try:
                if not container.is_visible(timeout=200):
                    continue
                text = normalize(container.inner_text(timeout=1000))
                if not COPYRIGHT_WARNING.search(text):
                    continue
                key = text[:240]
                if key not in seen:
                    seen.add(key)
                    yield container
            except (PlaywrightTimeout, PlaywrightError):
                continue

    # TikTok sometimes omits dialog semantics. In that case, climb only from an
    # exact warning anchor and require both Cancel and Share-now controls.
    anchors = page.get_by_text(
        re.compile(r"paylaşmaya devam edilsin mi|telif hakkı kontrolü eksik", re.I)
    )
    try:
        anchor_count = min(anchors.count(), 10)
    except PlaywrightError:
        anchor_count = 0
    for index in range(anchor_count):
        anchor = anchors.nth(index)
        if not _visible(anchor, 200):
            continue
        for depth in range(1, 9):
            container = anchor.locator(f"xpath=ancestor::*[{depth}]")
            try:
                text = normalize(container.inner_text(timeout=700))
                if not COPYRIGHT_WARNING.search(text):
                    continue
                has_cancel = _visible(container.get_by_text(CANCEL, exact=True), 150)
                has_share = _visible(
                    container.get_by_text(IMMEDIATE_SHARE, exact=True), 150
                )
                if has_cancel and has_share:
                    yield container
                    break
            except (PlaywrightTimeout, PlaywrightError):
                continue


def handle(page, timeout_seconds: float = 20.0) -> bool:
    """Cancel an incomplete-check publish attempt and raise a clear retry error."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for container in _verified_containers(page):
            if not _click_exact_cancel(container):
                raise CopyrightDialogError(
                    "Telif kontrolü tamamlanmadı ve İptal düğmesi bulunamadı; yayın durduruldu"
                )
            page.wait_for_timeout(500)
            raise CopyrightDialogError(
                "TikTok telif/içerik kontrolü henüz tamamlanmadı. "
                "'Hemen paylaş' kullanılmadı; kontrol bittikten sonra yeniden deneyin."
            )
        page.wait_for_timeout(200)
    return False
