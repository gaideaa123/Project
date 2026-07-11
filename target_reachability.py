from __future__ import annotations

"""Classify Playwright target probes without mistaking body aborts for tunnel failures."""

import re

_RESPONSE_STATUS = re.compile(r"(?:←|<-|response\s+status[:=]?)\s*(\d{3})", re.IGNORECASE)

def status_from_error(error: Exception | str) -> int | None:
 text = str(error)
 matches = _RESPONSE_STATUS.findall(text)
 if not matches:
  return None
 status = int(matches[-1])
 return status if 100 <= status <= 599 else None

def response_was_received(error: Exception | str) -> bool:
 """True only when Playwright logged an actual HTTP response from the target."""
 text = str(error)
 lowered = text.casefold()
 if "err_tunnel_connection_failed" in lowered:
  return False
 if "proxy connection" in lowered and "failed" in lowered:
  return False
 return status_from_error(text) is not None
