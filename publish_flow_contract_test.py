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
  assert window.publish_profiles_table.columnCount() == 7
  assert hasattr(window, "existing_variants_folder")
  assert hasattr(window, "distribute_existing_button")

  with tempfile.TemporaryDirectory() as folder:
   root = Path(folder)
   first = root / "1.mp4"; second = root / "2.mp4"; tenth = root / "10.mp4"
   first.write_bytes(b"video-1"); second.write_bytes(b"video-2")
   assert publishing_flow_gui.numbered_variants(root) == [first.resolve(), second.resolve()]
   tenth.write_bytes(b"video-10")
   try:
    publishing_flow_gui.numbered_variants(root)
    raise AssertionError("Eksik 3-9 sırası kabul edilmemeliydi")
   except RuntimeError as exc:
    assert "eksik" in str(exc).casefold()
   tenth.unlink()

   with patch.object(publishing_flow_gui, "registry_profiles", return_value=["A", "B"]), patch.object(
    publishing_flow_gui.network_identity, "load", side_effect=lambda name: identities[name]
   ), patch.object(publishing_flow_gui.proxy_health, "require_healthy"), patch.object(
    publishing_flow_gui, "save_settings", return_value=True
   ), patch.object(publishing_flow_gui, "start_publish") as start, patch.object(
    publishing_flow_gui, "save_secret"
   ):
    window._publish_profile_order = ["A", "B"]
    publishing_flow_gui.distribute_outputs(window, [first, second])
    assert window.pending_assignments == [("A", first.resolve()), ("B", second.resolve())]
    assert window.publish_profiles_table.item(0, 3).text() == identity_a.server
    start.assert_called_once_with(window)

    window.publish_worker = None
    publishing_flow_gui.move_profile(window, "B", -1)
    assert publishing_flow_gui.profiles(window) == ["B", "A"]
    assert window.pending_assignments == [("B", first.resolve()), ("A", second.resolve())]
    assert window.publish_profiles_table.item(0, 1).text() == "B"
    assert window.publish_profiles_table.item(0, 2).text() == "1.mp4"

   window.existing_variants_folder.setText(str(root))
   with patch.object(publishing_flow_gui, "distribute_outputs") as distribute:
    publishing_flow_gui.distribute_existing_variants(window)
    distribute.assert_called_once()
    files = distribute.call_args.args[1]
    assert files == [first.resolve(), second.resolve()]

   broken = root / "4.mp4"; broken.write_bytes(b"video-4")
   with patch.object(publishing_flow_gui.QMessageBox, "critical") as error:
    publishing_flow_gui.distribute_existing_variants(window)
    assert error.called
 finally:
  window.close(); app.processEvents()

 print("OK: hazır varyasyon dağıtımı ve kalıcı profil sırası doğrulandı")


if __name__ == "__main__":
 main()
