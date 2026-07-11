from __future__ import annotations

"""Automatic publish after completed checks, with safe dialog recovery."""

import re
import time
from typing import Any, Callable

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout, sync_playwright

import publication_guard
import upload_state

Status = Callable[[str], None]
PUBLISH_BUTTON = re.compile(r"^(paylaş|yayınla|gönder|post|publish|share)$", re.I)
CHECK_PENDING = re.compile(
    r"(?:içerik|telif|müzik).{0,80}(?:kontrol ediliyor|inceleniyor|sürüyor|bekleniyor|tamamlanmadı|eksik)|"
    r"(?:content|copyright|music).{0,80}(?:checking|in progress|processing|pending|not finished|incomplete)",
    re.I | re.S,
)
CHECK_COMPLETE = re.compile(
    r"sorun tespit edilmedi|kontrol(?:ler)? tamamlandı|kontrol tamamlandı|"
    r"no (?:issues?|problems?) (?:detected|found)|checks? (?:are )?complete|check completed|passed",
    re.I,
)
UPLOAD_PENDING = re.compile(
    r"(?:video\s*)?(?:yükleniyor|işleniyor|hazırlanıyor)\s*\d{0,3}\s*%?|"
    r"(?:uploading|processing)\s*(?:video)?\s*\d{0,3}\s*%?",
    re.I,
)
ADVISORY = re.compile(
    r"özgün olmayan, düşük kaliteli ve qr kodlu içerik|özgün olmayan ve düşük kaliteli içerik|"
    r"unoriginal, low-quality|qr code content|not eligible for recommendation",
    re.I,
)
INCOMPLETE_CHECK_DIALOG = re.compile(
    r"paylaşmaya devam edilsin mi|telif hakkı kontrolü eksik|"
    r"(?:h[âa]l[âa]|hala).{0,100}(?:kontrol ediyoruz|inceliyoruz)|"
    r"(?:copyright|content) check (?:is )?(?:incomplete|still in progress)|"
    r"continue (?:to )?(?:post|publish|share)",
    re.I | re.S,
)
DIALOG_CANCEL = re.compile(r"^(iptal|kapat|cancel|close)$", re.I)
DIALOG_SELECTORS = ('[role="dialog"]', '[role="alertdialog"]', '[aria-modal="true"]')
MAX_UPLOAD_RETRIES = 3
MAX_INCOMPLETE_DIALOG_RETRIES = 3


def _status(callback: Status | None, message: str) -> None:
    if callback:
        callback(message)


def _body(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=1800)
    except (PlaywrightTimeout, PlaywrightError):
        return ""


def _first_publish(page):
    locators = [
        page.get_by_role("button", name=PUBLISH_BUTTON),
        page.locator('button[data-e2e*="post" i]'),
        page.locator('button[data-e2e*="publish" i]'),
    ]
    for locator in locators:
        try:
            item = locator.first
            if item.is_visible(timeout=350):
                return item
        except (PlaywrightTimeout, PlaywrightError):
            continue
    return None


def _progress_busy(page) -> bool:
    bars = page.locator('[role="progressbar"]')
    try:
        count = min(bars.count(), 12)
    except PlaywrightError:
        return True
    for index in range(count):
        bar = bars.nth(index)
        try:
            if not bar.is_visible(timeout=100):
                continue
            value = bar.get_attribute("aria-valuenow")
            if value is None or float(value) < 100:
                return True
        except (PlaywrightError, ValueError):
            return True
    return False


def wait_for_checks_complete(
    page,
    status: Status | None = None,
    timeout_seconds: int = 900,
    require_completion_evidence: bool = False,
):
    deadline = time.monotonic() + timeout_seconds
    stable = 0
    last_notice = 0.0
    failure_key = ""
    failure_hits = 0
    retries = 0
    retry_quiet_until = 0.0

    while time.monotonic() < deadline:
        if page.is_closed():
            raise RuntimeError("TikTok penceresi içerik kontrolü tamamlanmadan kapatıldı")
        text = _body(page)
        now = time.monotonic()
        advisory = ADVISORY.search(text)
        if advisory:
            raise RuntimeError(
                "TikTok içeriği özgün olmayan/düşük kaliteli/QR kodlu olarak sınıflandırdı. "
                "'Yine de paylaş' seçilmedi; kaynak videoyu ve editoryal varyasyonu düzeltip yeniden üretin."
            )

        visible_failure = upload_state.visible_upload_failure(page)
        if visible_failure and now >= retry_quiet_until:
            key = visible_failure.text.casefold()
            failure_hits = failure_hits + 1 if key == failure_key else 1
            failure_key = key
            if failure_hits >= 3:
                if retries < MAX_UPLOAD_RETRIES and upload_state.click_retry(page, visible_failure):
                    retries += 1
                    failure_hits = 0
                    failure_key = ""
                    stable = 0
                    retry_quiet_until = now + 5
                    _status(
                        status,
                        f"TikTok yüklemesi başarısız oldu; Tekrar dene tıklandı ({retries}/{MAX_UPLOAD_RETRIES})",
                    )
                    page.wait_for_timeout(1500)
                    continue
                selected = upload_state.selected_file(page)
                detail = f" Seçili dosya: {selected[0]} ({selected[1]} bayt)." if selected else ""
                reason = (
                    "Tekrar dene düğmesi bulunamadı"
                    if retries < MAX_UPLOAD_RETRIES
                    else f"{MAX_UPLOAD_RETRIES} yeniden deneme başarısız oldu"
                )
                raise RuntimeError(
                    f"TikTok görünür yükleme hatası gösteriyor: {visible_failure.text}. {reason}.{detail}"
                )
        elif not visible_failure:
            failure_key = ""
            failure_hits = 0

        pending = bool(CHECK_PENDING.search(text) or UPLOAD_PENDING.search(text) or _progress_busy(page))
        completed = bool(CHECK_COMPLETE.search(text))
        button = _first_publish(page)
        enabled = False
        if button is not None:
            try:
                enabled = button.is_enabled()
            except PlaywrightError:
                enabled = False

        evidence_ok = completed or not require_completion_evidence
        if enabled and not pending and not visible_failure and evidence_ok:
            stable += 1
            if stable >= 3:
                _status(status, "Video yüklendi, içerik kontrolleri tamamlandı; Paylaş hazır")
                return button
        else:
            stable = 0

        if now - last_notice >= 8:
            _status(status, "Video yükleme ve içerik kontrolünün tamamlanması bekleniyor")
            last_notice = now
        page.wait_for_timeout(1000)
    raise RuntimeError("TikTok içerik kontrolünü 15 dakikada tamamlamadı")


def _click(locator, page) -> bool:
    try:
        locator.scroll_into_view_if_needed(timeout=2500)
    except (AttributeError, PlaywrightError):
        pass
    try:
        locator.click(timeout=5000)
        return True
    except PlaywrightError:
        try:
            locator.click(timeout=5000, force=True)
            return True
        except PlaywrightError:
            return False


def _dialog_cancel_button(dialog):
    try:
        button = dialog.get_by_role("button", name=DIALOG_CANCEL)
        if button.count() and button.first.is_visible(timeout=250):
            return button.first
    except (PlaywrightTimeout, PlaywrightError):
        pass
    try:
        candidates = dialog.locator("button, [role='button']")
        for index in range(min(candidates.count(), 20)):
            candidate = candidates.nth(index)
            label = re.sub(
                r"\s+",
                " ",
                candidate.get_attribute("aria-label") or candidate.inner_text(timeout=400) or "",
            ).strip()
            if DIALOG_CANCEL.fullmatch(label) and candidate.is_visible(timeout=200):
                return candidate
    except (PlaywrightTimeout, PlaywrightError):
        pass
    return None


def dismiss_incomplete_check_dialog(
    page,
    status: Status | None = None,
    timeout_seconds: float = 8.0,
) -> bool:
    """Dismiss only the incomplete-check warning; never click 'Hemen paylaş'."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if page.is_closed():
            return False
        for selector in DIALOG_SELECTORS:
            dialogs = page.locator(selector)
            try:
                count = min(dialogs.count(), 20)
            except PlaywrightError:
                continue
            for index in range(count):
                dialog = dialogs.nth(index)
                try:
                    if not dialog.is_visible(timeout=150):
                        continue
                    text = re.sub(r"\s+", " ", dialog.inner_text(timeout=700)).strip()
                    if not INCOMPLETE_CHECK_DIALOG.search(text):
                        continue
                    cancel = _dialog_cancel_button(dialog)
                    if cancel is None or not _click(cancel, page):
                        raise RuntimeError(
                            "TikTok eksik kontrol uyarısı açıldı fakat İptal/Kapat düğmesine tıklanamadı"
                        )
                    _status(status, "Eksik içerik kontrolü uyarısı İptal/Kapat ile kapatıldı; kontrol bekleniyor")
                    page.wait_for_timeout(500)
                    return True
                except (PlaywrightTimeout, PlaywrightError):
                    continue
        page.wait_for_timeout(200)
    return False


def install(web_uploader: Any) -> None:
    if getattr(web_uploader, "_automatic_publish_installed", False):
        return
    required = ("launch_context", "wait_for_login", "upload_file", "fill_caption", "goto_upload")
    if not all(callable(getattr(web_uploader, name, None)) for name in required):
        raise RuntimeError("Web uploader otomatik yayın için gerekli metotları sunmuyor")
    request_type = web_uploader.UploadRequest

    def prepare_upload(request, publish=False, approval=None, status=None):
        request.validate()
        with sync_playwright() as playwright:
            context = web_uploader.launch_context(playwright, request.profile)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                _status(status, f"{request.profile}: TikTok Studio açılıyor")
                web_uploader.goto_upload(page)
                web_uploader.wait_for_login(page)
                web_uploader.upload_file(page, request.video)
                selected = upload_state.selected_file(page)
                if selected and selected[1] <= 0:
                    raise RuntimeError("Tarayıcıya seçilen video dosyası boş")
                web_uploader.fill_caption(page, request.caption)

                require_completion_evidence = False
                for attempt in range(MAX_INCOMPLETE_DIALOG_RETRIES + 1):
                    button = wait_for_checks_complete(
                        page,
                        status=status,
                        require_completion_evidence=require_completion_evidence,
                    )
                    page.bring_to_front()
                    if not publish:
                        while context.pages:
                            page.wait_for_timeout(1000)
                        return

                    publication_guard.assert_publishable(page, status)
                    _status(status, f"{request.profile}: içerik kontrolü bitti, Paylaş tıklanıyor")
                    if not _click(button, page):
                        raise RuntimeError("TikTok Paylaş düğmesine tıklanamadı")
                    if not dismiss_incomplete_check_dialog(page, status=status):
                        break
                    if attempt >= MAX_INCOMPLETE_DIALOG_RETRIES:
                        raise RuntimeError(
                            "TikTok içerik kontrolü uyarısı tekrarlandı; Hemen paylaş seçilmeden akış durduruldu"
                        )
                    require_completion_evidence = True
                else:
                    raise RuntimeError("TikTok güvenli paylaşım denemeleri tamamlanamadı")

                publication_guard.wait_for_verified_publication(
                    page,
                    request.profile,
                    status=status,
                    timeout_seconds=180,
                )
            except Exception as exc:
                folder = web_uploader.save_diagnostics(page, request.profile, exc)
                raise web_uploader.UploadError(f"{exc}\nTanı dosyaları: {folder}") from exc
            finally:
                context.close()

    web_uploader.prepare_upload = prepare_upload
    web_uploader.UploadRequest = request_type
    web_uploader._automatic_publish_installed = True
