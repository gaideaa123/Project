from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import direct_connection_policy
import network_identity


def main() -> None:
 direct = network_identity.NetworkIdentity()
 proxied = network_identity.NetworkIdentity("socks5://proxy.example:1080", "u", "p")
 identities = {"Direct": direct, "Proxy": proxied}

 with patch.object(direct_connection_policy.network_identity, "load", side_effect=lambda name: identities[name]), patch.object(
  direct_connection_policy.proxy_health, "require_healthy"
 ) as healthy:
  result = direct_connection_policy.validate_connections(["Proxy", "Direct"])
  assert result["Proxy"] is proxied and result["Direct"] is direct
  healthy.assert_called_once_with(proxied)

 broken = RuntimeError("offline")
 with patch.object(direct_connection_policy.network_identity, "load", return_value=proxied), patch.object(
  direct_connection_policy.proxy_health, "require_healthy", side_effect=broken
 ):
  try:
   direct_connection_policy.connection_for("Proxy")
   raise AssertionError("Sağlıksız atanmış proxy direct bağlantıya düşmemeliydi")
  except RuntimeError as exc:
   assert "sağlıklı değil" in str(exc)

 module = SimpleNamespace()
 with patch.object(direct_connection_policy.network_identity, "_integrity_aware_delete_installed", True, create=True):
  direct_connection_policy.install(module)
 assert module.validated_proxy is direct_connection_policy.connection_for
 assert module.validate_proxy_assignments is direct_connection_policy.validate_connections

 print("OK: Atanmayan profil direct IP kullanıyor, atanmış sağlıksız proxy fallback yapmıyor")


if __name__ == "__main__":
 main()
