from __future__ import annotations

"""Bridge confirmed post-publication review notices to sequential success."""

from collections.abc import Callable
from typing import Any

from post_publish_outcome import is_published_review_notice


def install(web_uploader: Any) -> bool:
    """Wrap the final uploader exactly once, after every other installer."""
    if getattr(web_uploader, "_published_review_bridge_installed", False):
        return False
    original = getattr(web_uploader, "prepare_upload", None)
    if not callable(original):
        return False

    def prepare_upload(request, publish=False, approval=None, status=None):
        try:
            return original(
                request,
                publish=publish,
                approval=approval,
                status=status,
            )
        except Exception as exc:
            if not publish or not is_published_review_notice(exc):
                raise
            callback: Callable[[str], None] | None = status if callable(status) else None
            if callback:
                callback(
                    f"{request.profile}: video yayınlandı; TikTok incelemesi arka planda sürüyor, "
                    "sıradaki hesaba geçiliyor"
                )
            return None

    web_uploader.prepare_upload = prepare_upload
    web_uploader._published_review_bridge_installed = True
    return True
