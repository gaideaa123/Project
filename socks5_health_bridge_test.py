from __future__ import annotations

from unittest.mock import Mock, patch

import network_identity
import proxy_health


def main() -> None:
 identity = network_identity.NetworkIdentity("socks5://cdn.example:443", "user", "pass")
 bridge = Mock(); bridge.proxy = {"server": "http://127.0.0.1:41234"}; bridge.start.return_value = bridge
 session = Mock()
 with patch.object(proxy_health.socks_bridge, "AuthenticatedSocksBridge", return_value=bridge), patch.object(
  proxy_health, "_session", return_value=session
 ):
  with proxy_health._identity_session(identity) as actual:
   assert actual is session
  proxy_health._session.assert_called_once_with({
   "http": "http://127.0.0.1:41234", "https": "http://127.0.0.1:41234"
  })
  session.close.assert_called_once()
  bridge.close.assert_called_once()

 http_identity = network_identity.NetworkIdentity("http://proxy.example:8080", "u", "p")
 session = Mock()
 with patch.object(proxy_health, "_session", return_value=session) as create, patch.object(
  proxy_health.socks_bridge, "AuthenticatedSocksBridge"
 ) as bridge_class:
  with proxy_health._identity_session(http_identity):
   pass
  create.assert_called_once_with(network_identity.requests_proxies(http_identity))
  bridge_class.assert_not_called()

 with patch.object(proxy_health, "_direct_ip", return_value="9.9.9.9"), patch.object(
  proxy_health, "_fetch_ip", return_value="1.2.3.4"
 ), patch.object(proxy_health, "_geo_metadata", return_value=("TR", "AS1", "ISP", "")), patch.object(
  proxy_health, "record"
 ), patch.object(proxy_health, "_identity_session") as identity_session:
  identity_session.return_value.__enter__.return_value = Mock()
  result = proxy_health.test(identity, attempts=2)
  assert result.ok and result.exit_ip == "1.2.3.4"
  assert "InvalidSchema" not in result.detail

 print("OK: SOCKS5 sağlık testi PySocks olmadan localhost CONNECT bridge kullanıyor")


if __name__ == "__main__":
 main()
