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
 ):
  result = web_uploader.launch_context(playwright, "Profil A")
  assert result is good_context
  bad_context.close.assert_called_once()

 socks = network_identity.NetworkIdentity("socks5://proxy.example:443", "user", "pass")
 bridge = Mock(); bridge.proxy = {"server": "http://127.0.0.1:32123"}
 bridge.start.return_value = bridge
 playwright = Mock(); socks_context = Mock(); playwright.chromium.launch_persistent_context.return_value = socks_context
 with patch.object(web_uploader.network_identity, "load", return_value=socks), patch.object(
  web_uploader.socks_bridge, "AuthenticatedSocksBridge", return_value=bridge
 ), patch.object(web_uploader.proxy_health, "verify_browser_target"):
  result = web_uploader.launch_context(playwright, "Profil SOCKS")
  assert result is socks_context
  options = playwright.chromium.launch_persistent_context.call_args.kwargs
  assert options["proxy"] == bridge.proxy
  assert "username" not in options["proxy"]
  socks_context.on.assert_called_once()

 direct = network_identity.NetworkIdentity()
 with patch.object(web_uploader.network_identity, "load", return_value=direct):
  playwright = Mock(); context = Mock(); playwright.chromium.launch_persistent_context.return_value = context
  assert web_uploader.launch_context(playwright, "Profil B") is context

 context = Mock(); response = Mock(); response.status = 403
 context.request.get.return_value = response
 healthy = proxy_health.ProxyHealth("x", True, "1.2.3.4", "TR", 10, "2099-01-01T00:00:00+00:00")
 with patch.object(proxy_health, "verify_browser_context", return_value=healthy):
  assert proxy_health.verify_browser_target(context, identity, web_uploader.UPLOAD_URL) is healthy

 print("OK: HTTP, HTTPS ve kimlik doğrulamalı SOCKS5 tarayıcı yolları doğrulandı")


if __name__ == "__main__":
 main()
