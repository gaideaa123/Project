from __future__ import annotations

from unittest.mock import Mock, patch

import network_identity
import network_identity_gui


def installed_method(name: str):
 class Dummy:
  def build_ui(self): pass
  def refresh(self): pass
 network_identity_gui.install(Dummy)
 return getattr(Dummy, name)


def main() -> None:
 profiles = [f"P{index}" for index in range(1, 11)]
 identities = [network_identity.NetworkIdentity(f"socks5://proxy-{index}:1080", "u", "p") for index in range(1, 11)]
 window = Mock(); window._tested_source = "socks5\nsource"; window.proxy_source.return_value = "socks5\nsource"
 window._tested_identities = identities
 window._test_results = {index: Mock(ok=index in {1, 4, 8}) for index in range(10)}
 window.publish_profiles_table = Mock(); window.guide_profiles_page = Mock(); window.tabs = Mock()
 window.publish_status = Mock(); window.proxy_status = Mock(); window.refresh_proxy_mapping = Mock(); window.proxy_assign_button = Mock()

 with patch.object(network_identity_gui, "guide_profiles", return_value=profiles), patch.object(
  network_identity, "assign_in_order", return_value=list(zip(profiles[:3], [identities[1], identities[4], identities[8]]))
 ) as assign, patch.object(network_identity, "delete") as delete, patch("publishing_flow_gui.refresh_table") as refresh, patch.object(
  network_identity_gui.QMessageBox, "information"
 ):
  installed_method("assign_proxy_list")(window)
  assign.assert_called_once_with(profiles[:3], [identities[1], identities[4], identities[8]])
  assert [call.args[0] for call in delete.call_args_list] == profiles[3:]
  refresh.assert_called_once_with(window)
  window.tabs.setCurrentWidget.assert_called_once_with(window.guide_profiles_page)
  assert "7 profil Atanmadı" in window.publish_status.setText.call_args.args[0]

 ready_window = Mock(); ready_window._tested_source = "x"; ready_window.proxy_source.return_value = "x"
 ready_window._tested_identities = identities; ready_window._test_results = window._test_results
 ready_window.proxy_assign_button = Mock(); ready_window.proxy_status = Mock(); ready_window.refresh_proxy_mapping = Mock()
 with patch.object(network_identity_gui, "guide_profiles", return_value=profiles):
  installed_method("proxy_test_finished")(ready_window)
  ready_window.proxy_assign_button.setEnabled.assert_called_with(True)
  assert "3 profile atamaya hazır" in ready_window.proxy_status.setText.call_args.args[0]

 zero = Mock(); zero._tested_source = "x"; zero.proxy_source.return_value = "x"; zero._tested_identities = identities
 zero._test_results = {index: Mock(ok=False) for index in range(10)}; zero.proxy_assign_button = Mock(); zero.proxy_status = Mock(); zero.refresh_proxy_mapping = Mock()
 with patch.object(network_identity_gui, "guide_profiles", return_value=profiles):
  installed_method("proxy_test_finished")(zero)
  zero.proxy_assign_button.setEnabled.assert_called_with(False)

 print("OK: 10 profilde yalnız geçen proxyler kısmi atanıyor, kalanlar temizleniyor")


if __name__ == "__main__":
 main()
