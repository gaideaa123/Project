from __future__ import annotations

"""Regression contract: proxy, Cold Open and Session ID must ship together."""

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
        assert hasattr(window, "session_accounts_page"), "Session ID Hesapları kaldırılmış"

        uniquizer_index = window.tabs.indexOf(window.uniquizer_tab)
        proxy_index = window.tabs.indexOf(window.network_identity_page)
        session_index = window.tabs.indexOf(window.session_accounts_page)
        assert uniquizer_index >= 0
        assert proxy_index >= 0
        assert session_index >= 0
        assert window.tabs.tabText(uniquizer_index) == "Cold Open Uniquizer"
        assert window.tabs.tabText(proxy_index) == "Proxy Listesi"
        assert window.tabs.tabText(session_index) == "Session ID Hesapları"

        assert hasattr(window.uniquizer_tab, "input_video")
        assert hasattr(window.uniquizer_tab, "output_folder")
        assert hasattr(window.uniquizer_tab, "variant_count")
        assert hasattr(window, "proxy_list_input")
        assert hasattr(window, "proxy_test_button")
        assert hasattr(window, "proxy_assign_button")
        assert not window.proxy_assign_button.isEnabled()
        assert hasattr(window, "session_add_button")
        assert hasattr(window, "session_accounts_table")
        assert window.session_add_button.text() == "SESSION ID İLE YENİ HESAP EKLE"
    finally:
        window.close()
        app.processEvents()

    print("OK: Proxy, Cold Open ve Session ID hesap yönetimi birlikte korunuyor")


if __name__ == "__main__":
    main()
