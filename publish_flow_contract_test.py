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
    import publishing_flow_gui

    app = QApplication.instance() or QApplication([])
    window = app_tr.TurkceAnaPencere()
    try:
        assert hasattr(window, "guide_profiles_page")
        assert window.tabs.indexOf(window.guide_profiles_page) >= 0
        assert window.tabs.tabText(window.tabs.indexOf(window.guide_profiles_page)) == "Guide + Profiller"
        assert hasattr(window, "publish_guide")
        assert hasattr(window, "publish_profiles_table")
        assert window.publish_auto_start.isChecked()

        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "1.mp4"
            second = Path(folder) / "2.mp4"
            first.write_bytes(b"video-1")
            second.write_bytes(b"video-2")
            with patch.object(publishing_flow_gui, "profiles", return_value=["A", "B"]), patch.object(
                publishing_flow_gui, "save_settings", return_value=True
            ), patch.object(publishing_flow_gui, "start_publish") as start:
                publishing_flow_gui.distribute_outputs(window, [str(first), str(second)])
                assert window.pending_assignments == [("A", first.resolve()), ("B", second.resolve())]
                start.assert_called_once_with(window)
                assert window.tabs.currentWidget() is window.guide_profiles_page
    finally:
        window.close()
        app.processEvents()

    print("OK: Guide + Profiller dağıtımı otomatik yayın akışını başlatıyor")


if __name__ == "__main__":
    main()
