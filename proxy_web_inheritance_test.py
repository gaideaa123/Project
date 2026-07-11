from __future__ import annotations

from unittest.mock import Mock, patch

import network_identity
import web_uploader


def main() -> None:
 identity = network_identity.NetworkIdentity("http://proxy.example:8080", "alice", "secret")
 playwright = Mock()
 context = Mock()
 playwright.chromium.launch_persistent_context.return_value = context

 with patch.object(web_uploader.network_identity, "load", return_value=identity), patch.object(
  web_uploader.proxy_health, "require_healthy"
 ) as health:
  assert web_uploader.assigned_proxy("Profil A") == {
   "server": "http://proxy.example:8080", "username": "alice", "password": "secret"
  }
  web_uploader.launch_context(playwright, "Profil A")
  health.assert_called()
  options = playwright.chromium.launch_persistent_context.call_args.kwargs
  assert options["proxy"] == identity.playwright_proxy()

 with patch.object(web_uploader.network_identity, "load", return_value=network_identity.NetworkIdentity()):
  assert web_uploader.assigned_proxy("Profil B") is None

 print("OK: web uploader atanmış ve sağlıklı profil proxy'sini Chromium'a devralıyor")


if __name__ == "__main__":
 main()
