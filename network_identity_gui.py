from __future__ import annotations

"""Bulk one-proxy-per-account configuration tab."""

from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import network_identity


def install(window_class) -> None:
    if getattr(window_class, "_network_identity_gui_installed", False):
        return
    original_build = window_class.build_ui
    original_refresh = window_class.refresh

    def network_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("Hesap Başına Sabit Proxy")
        title.setStyleSheet("font-size: 20px; font-weight: 700")
        layout.addWidget(title)
        guide = QLabel(
            "Proxy listesini satır satır yapıştırın. Desteklenen format: "
            "host:port:kullanıcı:parola. İlk proxy ilk hesaba, ikinci proxy ikinci "
            "hesaba atanır. Atama kalıcıdır; rotasyon yapılmaz ve proxy parolaları "
            "işletim sistemi güvenli kasasında tutulur."
        )
        guide.setWordWrap(True)
        layout.addWidget(guide)
        scheme_row = QHBoxLayout()
        scheme_row.addWidget(QLabel("Proxy tipi"))
        self.proxy_scheme = QComboBox()
        self.proxy_scheme.addItems(["http", "https", "socks5"])
        scheme_row.addWidget(self.proxy_scheme)
        scheme_row.addStretch()
        layout.addLayout(scheme_row)
        self.proxy_list_input = QPlainTextEdit()
        self.proxy_list_input.setPlaceholderText(
            "31.59.20.176:6754:kullanici:parola\n"
            "31.56.127.193:7684:kullanici:parola"
        )
        self.proxy_list_input.setMinimumHeight(150)
        layout.addWidget(self.proxy_list_input)
        actions = QHBoxLayout()
        assign = QPushButton("PROXYLERİ HESAPLARA SIRAYLA ATA")
        assign.clicked.connect(self.assign_proxy_list)
        clear = QPushButton("Tüm proxy atamalarını kaldır")
        clear.clicked.connect(self.clear_all_proxy_assignments)
        actions.addWidget(assign)
        actions.addWidget(clear)
        actions.addStretch()
        layout.addLayout(actions)
        self.proxy_mapping = QTableWidget(0, 3)
        self.proxy_mapping.setHorizontalHeaderLabels(["Sıra", "Hesap", "Sabit proxy"])
        self.proxy_mapping.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.proxy_mapping)
        self.proxy_status = QLabel("Hazır")
        self.proxy_status.setWordWrap(True)
        layout.addWidget(self.proxy_status)
        return page

    def refresh_proxy_mapping(self):
        profiles = self.account_names() if hasattr(self, "account_names") else []
        self.proxy_mapping.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            identity = network_identity.load(profile)
            self.proxy_mapping.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self.proxy_mapping.setItem(row, 1, QTableWidgetItem(profile))
            self.proxy_mapping.setItem(
                row, 2, QTableWidgetItem(identity.server or "Doğrudan bağlantı")
            )

    def assign_proxy_list(self):
        profiles = self.account_names() if hasattr(self, "account_names") else []
        try:
            identities = network_identity.parse_proxy_list(
                self.proxy_list_input.toPlainText(), self.proxy_scheme.currentText()
            )
            assignments = network_identity.assign_in_order(profiles, identities)
            refresh_proxy_mapping(self)
            self.proxy_status.setText(
                f"{len(assignments)} hesap sabit proxy ile eşleştirildi. "
                "Yeni ayar bir sonraki Chrome açılışında devreye girer."
            )
            self.proxy_list_input.clear()
            QMessageBox.information(
                self, "Proxy ataması tamamlandı",
                f"{len(assignments)} hesaba sırayla birer sabit proxy atandı.",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Proxy listesi hatası", str(exc))

    def clear_all_proxy_assignments(self):
        profiles = self.account_names() if hasattr(self, "account_names") else []
        for profile in profiles:
            network_identity.delete(profile)
        refresh_proxy_mapping(self)
        self.proxy_status.setText("Tüm hesaplar doğrudan bağlantıya döndürüldü")

    def build_ui(self):
        original_build(self)
        self.network_identity_page = network_tab(self)
        self.tabs.addTab(self.network_identity_page, "Proxy Listesi")
        refresh_proxy_mapping(self)

    def refresh(self):
        original_refresh(self)
        if hasattr(self, "proxy_mapping"):
            refresh_proxy_mapping(self)

    window_class.build_ui = build_ui
    window_class.refresh = refresh
    window_class.network_tab = network_tab
    window_class.refresh_proxy_mapping = refresh_proxy_mapping
    window_class.assign_proxy_list = assign_proxy_list
    window_class.clear_all_proxy_assignments = clear_all_proxy_assignments
    window_class._network_identity_gui_installed = True
