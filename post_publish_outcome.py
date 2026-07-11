from __future__ import annotations

"""Classify post-publication review notices without masking real publish failures."""

import re

PUBLISHED_REVIEW = re.compile(
    r"gönderi\s+yayınlandı\s+ancak\s+erişim\s+riski\s+görüldü\s*:\s*"
    r"(?:inceleniyor|incelemede|reviewing|under review)",
    re.I,
)


def is_published_review_notice(error: BaseException) -> bool:
    """True only when the error itself confirms publication and review state."""
    return PUBLISHED_REVIEW.search(str(error)) is not None
