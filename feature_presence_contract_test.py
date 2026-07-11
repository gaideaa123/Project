from __future__ import annotations

"""Regression contract: proxy and Cold Open features must ship together."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")


def main() -> None:
    from PySide6.QtWidgets import QApplication
    import app_tr

    app = QApplication.instance() or QApplication([])
    window = app_tr.TurkceAnaPencere()
    try:
        assert window.uniquizer_tab is not None, "Cold Open Uniquizer kaldırılmış"
        assert hasattr(window, "network_identity_page"), "Proxy Listesi kaldırılmış"

        uniquizer_index = window.tabs.indexOf(window.uniquizer_tab)
        proxy_index = window.tabs.indexOf(window.network_identity_page)
        assert uniquizer_index >= 0, "Cold Open Uniquizer sekmeye eklenmemiş"
        assert proxy_index >= 0, "Proxy Listesi sekmeye eklenmemiş"
        assert window.tabs.tabText(uniquizer_index) == "Cold Open Uniquizer"
        assert window.tabs.tabText(proxy_index) == "Proxy Listesi"

        assert hasattr(window.uniquizer_tab, "input_video")
        assert hasattr(window.uniquizer_tab, "output_folder")
        assert hasattr(window.uniquizer_tab, "variant_count")
        assert hasattr(window.uniquizer_tab, "outputs_ready")

        assert hasattr(window, "proxy_list_input")
        assert hasattr(window, "proxy_test_button")
        assert hasattr(window, "proxy_assign_button")
        assert not window.proxy_assign_button.isEnabled(), (
            "Proxy atama düğmesi test yapılmadan açık olmamalı"
        )
    finally:
        window.close()
        app.processEvents()

    print("OK: Proxy Listesi ve Cold Open Uniquizer birlikte korunuyor")


if __name__ == "__main__":
    main()
