from __future__ import annotations

"""Bounded retry for page navigation when a rotating SOCKS5 tunnel flakes."""

import re
from typing import Any

TRANSIENT = re.compile(
 r"ERR_TUNNEL_CONNECTION_FAILED|ERR_PROXY_CONNECTION_FAILED|"
 r"ERR_CONNECTION_RESET|ERR_CONNECTION_CLOSED|ERR_TIMED_OUT|"
 r"proxy.*(?:failed|closed)|tunnel.*failed",
 re.I,
)
MAX_ATTEMPTS = 3
BACKOFF_MS = (1500, 3000)

class NavigationRetryError(RuntimeError):
 pass

def is_transient(error: Exception | str) -> bool:
 return bool(TRANSIENT.search(str(error)))

def install(web_uploader: Any) -> None:
 if getattr(web_uploader, "_navigation_retry_installed", False):
  return
 original = getattr(web_uploader, "goto_upload", None)
 if not callable(original):
  raise NavigationRetryError("Web uploader goto_upload metodu bulunamadı")

 def goto_upload(page) -> None:
  errors: list[str] = []
  for attempt in range(1, MAX_ATTEMPTS + 1):
   try:
    original(page)
    return
   except Exception as exc:
    if not is_transient(exc):
     raise
    errors.append(str(exc).splitlines()[0][:300])
    if attempt >= MAX_ATTEMPTS:
     break
    try:
     page.goto("about:blank", wait_until="commit", timeout=5000)
    except Exception:
     pass
    page.wait_for_timeout(BACKOFF_MS[attempt - 1])
  raise NavigationRetryError(
   f"SOCKS5 proxy TikTok sayfa tünelini {MAX_ATTEMPTS} denemede kuramadı. "
   "Proxy hedef testi geçse de dönen upstream bağlantılardan biri kararsız. "
   "Aynı ülke için sticky/session proxy kullanın veya sağlayıcıda IP değiştirin. "
   f"Son hatalar: {' | '.join(errors)}"
  )

 web_uploader.goto_upload = goto_upload
 web_uploader._navigation_retry_installed = True
