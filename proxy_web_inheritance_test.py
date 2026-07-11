from __future__ import annotations

from unittest.mock import Mock, patch

import network_identity
import proxy_health
import web_uploader


def main() -> None:
 identity = network_identity.NetworkIdentity("https://proxy.example:8080", "alice", "secret")
 candidates = web_uploader.browser_proxy_candidates(identity)
 assert candidates[0] == {"server": "https://proxy.example:8080", "username": "alice", "password": "secret"}
 assert candidates[1]["server"] == "http://proxy.example:8080"

 playwright = Mock(); bad_context = Mock(); good_context = Mock()
 playwright.chromium.launch_persistent_context.side_effect = [bad_context, good_context]
 with patch.object(web_uploader.network_identity, "load", return_value=identity), patch.object(
  web_uploader.proxy_health, "verify_browser_target", side_effect=[RuntimeError("ERR_TUNNEL_CONNECTION_FAILED"), Mock()]
 ) as verify:
  result = web_uploader.launch_context(playwright, "Profil A")
  assert result is good_context
  assert verify.call_count == 2
  bad_context.close.assert_called_once()
  first = playwright.chromium.launch_persistent_context.call_args_list[0].kwargs["proxy"]
  second = playwright.chromium.launch_persistent_context.call_args_list[1].kwargs["proxy"]
  assert first["server"].startswith("https://")
  assert second["server"].startswith("http://")

 direct = network_identity.NetworkIdentity()
 with patch.object(web_uploader.network_identity, "load", return_value=direct):
  playwright = Mock(); context = Mock(); playwright.chromium.launch_persistent_context.return_value = context
  assert web_uploader.launch_context(playwright, "Profil B") is context

 context = Mock(); response = Mock(); response.status = 403
 context.request.get.return_value = response
 healthy = proxy_health.ProxyHealth("x", True, "1.2.3.4", "TR", 10, "2099-01-01T00:00:00+00:00")
 with patch.object(proxy_health, "verify_browser_context", return_value=healthy):
  assert proxy_health.verify_browser_target(context, identity, web_uploader.UPLOAD_URL) is healthy

 print("OK: TikTok tüneli hedef bazlı doğrulanıyor ve HTTPS proxy için güvenli CONNECT fallback çalışıyor")


if __name__ == "__main__":
 main()
