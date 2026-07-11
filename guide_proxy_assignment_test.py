from __future__ import annotations

from unittest.mock import Mock, patch

import network_identity
import network_identity_gui


def main() -> None:
 window = Mock()
 window._tested_source = "socks5\nsource"
 window.proxy_source.return_value = "socks5\nsource"
 window._tested_identities = [
  network_identity.NetworkIdentity("socks5://bad:1", "u", "p"),
  network_identity.NetworkIdentity("socks5://good-a:2", "u", "p"),
  network_identity.NetworkIdentity("socks5://good-b:3", "u", "p"),
 ]
 window._test_results = {0: Mock(ok=False), 1: Mock(ok=True), 2: Mock(ok=True)}
 window.publish_profiles_table = Mock(); window.guide_profiles_page = Mock(); window.tabs = Mock()
 window.publish_status = Mock(); window.proxy_status = Mock(); window.refresh_proxy_mapping = Mock()

 with patch.object(network_identity_gui, "guide_profiles", return_value=["B", "A"]), patch.object(
  network_identity, "assign_in_order", return_value=[("B", window._tested_identities[1]), ("A", window._tested_identities[2])]
 ) as assign, patch("publishing_flow_gui.refresh_table") as refresh, patch.object(
  network_identity_gui.QMessageBox, "information"
 ):
  # Call the method installed on a tiny class so the real implementation is exercised.
  class Dummy:
   def build_ui(self): pass
   def refresh(self): pass
  network_identity_gui.install(Dummy)
  Dummy.assign_proxy_list(window)
  assign.assert_called_once_with(["B", "A"], [window._tested_identities[1], window._tested_identities[2]])
  refresh.assert_called_once_with(window)
  window.tabs.setCurrentWidget.assert_called_once_with(window.guide_profiles_page)
  assert "B=socks5://good-a:2" in window.publish_status.setText.call_args.args[0]

 print("OK: yalnız testi geçen proxyler Guide + Profiller sırasına atanıyor")


if __name__ == "__main__":
 main()
