from __future__ import annotations

"""Batch policy for TikTok copyright confirmation.

The ordered distributor maps 1.mp4 to the first profile, 2.mp4 to the second,
and so on. Only 1.mp4 may need the initial Hemen paylaş confirmation because
Kapat disables content checks for the later new-account sessions.
"""

from pathlib import Path


def is_first_profile_video(video: Path) -> bool:
    """Return True only for the exact first numbered output, 1.mp4."""
    path = Path(video)
    return path.suffix.casefold() == ".mp4" and path.stem == "1"
