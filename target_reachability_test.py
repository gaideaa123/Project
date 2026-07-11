from __future__ import annotations

from unittest.mock import Mock, patch

import network_identity
import proxy_health
import target_reachability


def main() -> None:
 received = RuntimeError("APIRequestContext.get: aborted\nCall log:\n- ← 200 OK\n- content-type: text/html")
 assert target_reachability.status_from_error(received) == 200
 assert target_reachability.response_was_received(received)
 assert target_reachability.response_was_received(RuntimeError("aborted\n<- 403 Forbidden"))
 assert not target_reachability.response_was_received(RuntimeError("ERR_TUNNEL_CONNECTION_FAILED\n← 502 Bad Gateway"))
 assert not target_reachability.response_was_received(RuntimeError("APIRequestContext.get: aborted"))

 identity = network_identity.NetworkIdentity("socks5://proxy.example:1080", "u", "p")
 context = Mock(); context.request.get.side_effect = received
 healthy = proxy_health.ProxyHealth("x", True, "1.2.3.4", "TR", 10, "2099-01-01T00:00:00+00:00")
 with patch.object(proxy_health, "verify_browser_context", return_value=healthy):
  assert proxy_health.verify_browser_target(context, identity, "https://www.tiktok.com/") is healthy

 tunnel = RuntimeError("APIRequestContext.get: ERR_TUNNEL_CONNECTION_FAILED")
 context.request.get.side_effect = tunnel
 with patch.object(proxy_health, "verify_browser_context", return_value=healthy):
  try:
   proxy_health.verify_browser_target(context, identity, "https://www.tiktok.com/")
   raise AssertionError("Tunnel hatası başarı sayılmamalıydı")
  except proxy_health.ProxyHealthError as exc:
   assert "tüneli" in str(exc)

 print("OK: TikTok 200/403 response sonrası aborted erişilebilir, gerçek tunnel hatası başarısız")


if __name__ == "__main__":
 main()
