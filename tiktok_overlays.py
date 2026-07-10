from __future__ import annotations

"""Dismiss optional TikTok onboarding overlays for a newly used profile.

Only visible, exact-labelled controls inside modal/banner containers are clicked.
Copyright and publish confirmations are deliberately excluded.
"""

import re
import time
from collections.abc import Callable

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

StatusCallback = Callable[[str], None]
COOKIE_ALLOW = re.compile(
    r"^(tümüne izin ver|tüm çerezlere izin ver|çerezlere izin ver|"
    r"allow all|allow all cookies|accept all|accept all cookies)$",
    re.I,
)
CLOSE = re.compile(r"^(kapat|close)$", re.I)
GOT_IT = re.compile(r"^(anladım|tamam|got it|understood|i understand)$", re.I)
EXCLUDED_TEXT = re.compile(
    r"telif|copyright|paylaşmaya devam|publish|post|share|yayınla|paylaş",
    re.I,
)
CONTAINER_SELECTORS = (
    '[role="dialog"]',
    '[aria-modal="true"]',
    '[role="alertdialog"]',
    '[class*="modal" i]',
    '[class*="dialog" i]',
    '[class*="banner" i]',
    '[class*="cookie" i]',
)


def _notify(status: StatusCallback | None, message: str) -> None:
    if status:
        status(message)


def _visible(locator, timeout: int = 250) -> bool:
    try:
        return bool(locator.count() and locator.first.is_visible(timeout=timeout))
    except (PlaywrightTimeout, PlaywrightError):
        return False


def _containers(page):
    seen: set[str] = set()
    for selector in CONTAINER_SELECTORS:
        locators = page.locator(selector)
        try:
            count = min(locators.count(), 30)
        except PlaywrightError:
            count = 0
        for index in range(count):
            container = locators.nth(index)
            try:
                if not container.is_visible(timeout=150):
                    continue
                text = re.sub(r"\s+", " ", container.inner_text(timeout=700)).strip()
                key = f"{selector}:{text[:180]}"
                if key not in seen:
                    seen.add(key)
                    yield container, text
            except (PlaywrightTimeout, PlaywrightError):
                continue


def _click_exact(container, pattern: re.Pattern[str]) -> bool:
    button = container.get_by_role("button", name=pattern)
    if _visible(button, 300):
        button.first.click(timeout=4000)
        return True
    text = container.get_by_text(pattern, exact=True)
    if _visible(text, 300):
        target = text.first
        try:
            target.click(timeout=4000)
        except PlaywrightError:
            target.locator(
                "xpath=ancestor::*[self::button or @role='button'][1]"
            ).click(timeout=4000)
        return True
    candidates = container.locator("button, [role='button']")
    try:
        count = min(candidates.count(), 30)
    except PlaywrightError:
        count = 0
    for index in range(count):
        candidate = candidates.nth(index)
        try:
            label = re.sub(
                r"\s+", " ",
                candidate.get_attribute("aria-label")
                or candidate.inner_text(timeout=400)
                or "",
            ).strip()
            if pattern.fullmatch(label) and candidate.is_visible(timeout=200):
                candidate.click(timeout=4000)
                return True
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return False


def _click_cookie(page, status=None) -> bool:
    for container, text in _containers(page):
        if EXCLUDED_TEXT.search(text):
            continue
        if _click_exact(container, COOKIE_ALLOW):
            _notify(status, "Çerez izni kabul edildi")
            page.wait_for_timeout(300)
            return True
    # Cookie banners are sometimes not modal-like; exact global label is safe.
    global_button = page.get_by_role("button", name=COOKIE_ALLOW)
    if _visible(global_button, 250):
        global_button.first.click(timeout=4000)
        _notify(status, "Çerez izni kabul edildi")
        page.wait_for_timeout(300)
        return True
    return False


def _click_close(page, status=None) -> bool:
    for container, text in _containers(page):
        if EXCLUDED_TEXT.search(text):
            continue
        if _click_exact(container, CLOSE):
            _notify(status, "Yeni hesap uyarısı Kapat ile kapatıldı")
            page.wait_for_timeout(300)
            return True
    return False


def _click_got_it(page, status=None) -> bool:
    for container, text in _containers(page):
        if EXCLUDED_TEXT.search(text):
            continue
        if _click_exact(container, GOT_IT):
            _notify(status, "TikTok bilgilendirmesi Anladım ile kapatıldı")
            page.wait_for_timeout(300)
            return True
    return False


def clear_new_account_overlays(
    page,
    status: StatusCallback | None = None,
    timeout_seconds: float = 20.0,
    quiet_seconds: float = 1.5,
) -> int:
    """Clear cookie -> Kapat -> every Anladım until the page remains quiet."""
    deadline = time.monotonic() + timeout_seconds
    clicks = 0
    stage = "cookie"
    quiet_since = time.monotonic()

    while time.monotonic() < deadline:
        if page.is_closed():
            return clicks
        clicked = False
        if stage == "cookie":
            clicked = _click_cookie(page, status)
            stage = "close"
        elif stage == "close":
            clicked = _click_close(page, status)
            # Even when Kapat is absent, advance to repeated onboarding notices.
            stage = "got_it"
        else:
            # Some TikTok flows show another Kapat between Anladım dialogs.
            clicked = _click_close(page, status) or _click_got_it(page, status)

        if clicked:
            clicks += 1
            quiet_since = time.monotonic()
            continue
        if stage != "got_it":
            continue
        if time.monotonic() - quiet_since >= quiet_seconds:
            return clicks
        page.wait_for_timeout(150)
    return clicks
