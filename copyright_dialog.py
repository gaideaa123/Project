from __future__ import annotations

"""TikTok incomplete-copyright-check confirmation handling."""

import re
import time

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

# Exact wording observed in the current Turkish TikTok Studio modal, plus
# equivalent older/English variants. Whitespace is normalized before matching.
COPYRIGHT_WARNING = re.compile(
    r"paylaşmaya devam edilsin mi|"
    r"telif hakkı kontrolü eksik|"
    r"kontrol tamamlanmadan önce paylaşmaya devam etmek ister misiniz|"
    r"copyright check.*(?:incomplete|not finished|has not finished|in progress)|"
    r"continue (?:sharing|posting|publishing).*(?:copyright|check)",
    re.I,
)
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


def _click_immediate_share(container) -> bool:
    """Click exact Hemen paylaş within one already verified modal container."""
    by_role = container.get_by_role("button", name=IMMEDIATE_SHARE)
    if _visible(by_role, 400):
        by_role.first.click(timeout=5000)
        return True

    # Current TikTok markup may put the accessible text in a nested span.
    by_text = container.get_by_text(IMMEDIATE_SHARE, exact=True)
    if _visible(by_text, 400):
        target = by_text.first
        try:
            target.click(timeout=5000)
        except PlaywrightError:
            parent = target.locator(
                "xpath=ancestor::*[self::button or @role='button'][1]"
            )
            parent.click(timeout=5000)
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
            if IMMEDIATE_SHARE.fullmatch(label) and candidate.is_visible(timeout=300):
                candidate.click(timeout=5000)
                return True
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return False


def _verified_containers(page):
    """Yield visible modal-like containers whose text is the copyright warning."""
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
                key = f"{selector}:{text[:160]}"
                if key not in seen:
                    seen.add(key)
                    yield container
            except (PlaywrightTimeout, PlaywrightError):
                continue

    # Last fallback for TikTok builds without dialog/aria-modal semantics:
    # locate the exact heading/body and climb to the smallest ancestor that also
    # contains both İptal and Hemen paylaş. It never scans/clicks the whole page.
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
                has_share = _visible(
                    container.get_by_text(IMMEDIATE_SHARE, exact=True), 150
                )
                has_cancel = _visible(
                    container.get_by_text(CANCEL, exact=True), 150
                )
                if has_share and has_cancel:
                    yield container
                    break
            except (PlaywrightTimeout, PlaywrightError):
                continue


def handle(page, timeout_seconds: float = 20.0) -> bool:
    """Find the verified incomplete-check modal and click exact Hemen paylaş."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        found_warning = False
        for container in _verified_containers(page):
            found_warning = True
            if _click_immediate_share(container):
                # Wait until the modal disappears or navigation begins. This avoids
                # closing the browser context while TikTok is processing the click.
                for _ in range(20):
                    try:
                        if not container.is_visible(timeout=150):
                            return True
                    except PlaywrightError:
                        return True
                    page.wait_for_timeout(100)
                return True
        if found_warning:
            raise CopyrightDialogError(
                "Telif kontrolü modalı görüldü fakat 'Hemen paylaş' tıklanamadı"
            )
        page.wait_for_timeout(200)
    return False
