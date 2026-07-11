from __future__ import annotations

"""Install content preflight around the existing web uploader without UI drift."""

from typing import Any

import content_preflight


def install(web_uploader: Any) -> None:
    if getattr(web_uploader, "_signaldesk_preflight_installed", False):
        return
    original_prepare = web_uploader.prepare_upload

    def prepare(request, publish=False, approval=None, status=None):
        if status:
            status(f"{request.profile}: medya kalite ve tekrar kontrolü yapılıyor")
        report = content_preflight.validate(
            request.profile, request.video, request.caption
        )
        result = original_prepare(
            request, publish=publish, approval=approval, status=status
        )
        if publish:
            content_preflight.record(request.profile, report, "published")
        return result

    web_uploader.prepare_upload = prepare
    web_uploader._signaldesk_preflight_installed = True
