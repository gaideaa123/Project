from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")


def main() -> None:
 from PySide6.QtWidgets import QApplication
 import app_tr
 import network_identity
 import publishing_flow_gui

 app = QApplication.instance() or QApplication([])
 window = app_tr.TurkceAnaPencere()
 identity_a = network_identity.NetworkIdentity("http://127.0.0.1:8001", "user-a", "pass-a")
 identity_b = network_identity.NetworkIdentity("http://127.0.0.1:8002", "user-b", "pass-b")
 identities = {"A": identity_a, "B": identity_b}
 try:
  assert hasattr(window, "guide_profiles_page")
  assert window.tabs.indexOf(window.guide_profiles_page) >= 0
  assert window.tabs.tabText(window.tabs.indexOf(window.guide_profiles_page)) == "Guide + Profiller"
  assert window.publish_profiles_table.columnCount() == 6
  assert window.publish_auto_start.isChecked()

  with tempfile.TemporaryDirectory() as folder:
   first = Path(folder) / "1.mp4"; second = Path(folder) / "2.mp4"
   first.write_bytes(b"video-1"); second.write_bytes(b"video-2")
   with patch.object(publishing_flow_gui, "profiles", return_value=["A", "B"]), patch.object(
    publishing_flow_gui.network_identity, "load", side_effect=lambda name: identities[name]
   ), patch.object(publishing_flow_gui.proxy_health, "require_healthy"), patch.object(
    publishing_flow_gui, "save_settings", return_value=True
   ), patch.object(publishing_flow_gui, "start_publish") as start:
    publishing_flow_gui.distribute_outputs(window, [str(first), str(second)])
    assert window.pending_assignments == [("A", first.resolve()), ("B", second.resolve())]
    assert window.publish_profiles_table.item(0, 1).text() == "A"
    assert window.publish_profiles_table.item(0, 2).text() == "1.mp4"
    assert window.publish_profiles_table.item(0, 3).text() == identity_a.server
    assert window.publish_profiles_table.item(0, 5).text() == "Atandı"
    assert "A=1.mp4@http://127.0.0.1:8001" in window.publish_status.text()
    start.assert_called_once_with(window)
    assert window.tabs.currentWidget() is window.guide_profiles_page

   with patch.object(publishing_flow_gui, "profiles", return_value=["A"]), patch.object(
    publishing_flow_gui.network_identity, "load", return_value=network_identity.NetworkIdentity()
   ), patch.object(publishing_flow_gui.QMessageBox, "critical") as error:
    publishing_flow_gui.distribute_outputs(window, [str(first)])
    assert error.called
    assert "Proxy Listesi" in window.publish_status.text()
 finally:
  window.close(); app.processEvents()

 print("OK: app_tr video, profil ve test edilmiş proxyyi birlikte dağıtıyor")


if __name__ == "__main__":
 main()
