from __future__ import annotations

"""TikTok copyright warning confirmation, scoped to the verified dialog."""

import re
import time

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

COPYRIGHT_WARNING = re.compile(
    r"copyright check.*(?:not|hasn't|has not).*finished|"
    r"copyright check.*in progress|"
    r"telif hakkı.*(?:henüz )?bitmedi|"
    r"telif.*kontrol.*(?:tamamlanmadı|devam ediyor)",
    re.I,
)
IMMEDIATE_SHARE = re.compile(
    r"^(hemen paylaş|hemen yayınla|şimdi paylaş|şimdi yayınla|"
    r"share now|publish now|post now)$",
    re.I,
)


class CopyrightDialogError(RuntimeError):
    pass


def handle(page, timeout_seconds: float = 15.0) -> bool:
    """Click exact Hemen paylaş/Share now only inside a copyright warning dialog."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        dialogs = page.get_by_role("dialog")
        try:
            count = min(dialogs.count(), 5)
        except PlaywrightError:
            count = 0
        for index in range(count):
            dialog = dialogs.nth(index)
            try:
                if not dialog.is_visible(timeout=250):
                    continue
                text = dialog.inner_text(timeout=1200)
                if not COPYRIGHT_WARNING.search(text):
                    continue

                # Accessible-name lookup first. This handles nested spans inside the button.
                button = dialog.get_by_role("button", name=IMMEDIATE_SHARE)
                if button.count() and button.first.is_visible(timeout=500):
                    button.first.click(timeout=5000)
                    return True

                # TikTok sometimes renders a clickable div rather than a semantic button.
                text_target = dialog.get_by_text(IMMEDIATE_SHARE, exact=True)
                if text_target.count() and text_target.first.is_visible(timeout=500):
                    target = text_target.first
                    try:
                        target.click(timeout=5000)
                    except PlaywrightError:
                        target.locator("xpath=ancestor::*[self::button or @role='button'][1]").click(timeout=5000)
                    return True

                # Last fallback stays scoped to the already verified copyright dialog.
                candidates = dialog.locator("button, [role='button']")
                for candidate_index in range(min(candidates.count(), 20)):
                    candidate = candidates.nth(candidate_index)
                    label = (candidate.inner_text(timeout=500) or "").strip()
                    if IMMEDIATE_SHARE.fullmatch(label) and candidate.is_visible(timeout=300):
                        candidate.click(timeout=5000)
                        return True
                raise CopyrightDialogError(
                    "Telif uyarısı görüldü fakat 'Hemen paylaş' düğmesi bulunamadı"
                )
            except PlaywrightTimeout:
                continue
        page.wait_for_timeout(200)
    return False
