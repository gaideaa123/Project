from __future__ import annotations

"""Classify post-publication review notices without masking real failures."""

import re

PUBLISHED_REVIEW = re.compile(
    r"(?:gönderi|video)\s+(?:başarıyla\s+)?(?:yayınlandı|paylaşıldı)\s*[,;.]?\s*"
    r"ancak\s+erişim\s+riski\s+görüldü\s*:\s*"
    r"(?:inceleniyor|incelemede|reviewing|under\s+review)\b",
    re.I,
)


def normalize_notice(value: object) -> str:
    """Collapse UI line breaks and duplicated spacing before classification."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_published_review_notice(error: BaseException) -> bool:
    """True only when the notice confirms both publication and review state."""
    return PUBLISHED_REVIEW.search(normalize_notice(error)) is not None
