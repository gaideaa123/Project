from __future__ import annotations

"""Small configuration tab for fixed per-profile network gateways."""

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
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
        note = QLabel(
            "Her profile opsiyonel olarak tek, sabit ve size ait bir ağ geçidi bağlayın. "
            "Rotasyon yapılmaz; aynı profil her açılışta aynı geçidi kullanır. Boş bırakırsanız "
            "normal internet bağlantısı kullanılır."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.network_profile = QComboBox()
        self.network_profile.currentTextChanged.connect(self.load_network_identity)
        self.network_server = QLineEdit()
        self.network_server.setPlaceholderText("http://host:port veya socks5://host:port")
        self.network_username = QLineEdit()
        self.network_password = QLineEdit()
        self.network_password.setEchoMode(QLineEdit.Password)
        form.addRow("Profil", self.network_profile)
        form.addRow("Sabit ağ geçidi", self.network_server)
        form.addRow("Kullanıcı", self.network_username)
        form.addRow("Parola", self.network_password)
        layout.addLayout(form)
        actions = QHBoxLayout()
        save = QPushButton("PROFİLE SABİT AĞ GEÇİDİ BAĞLA")
        clear = QPushButton("Bu profil için doğrudan bağlantı kullan")
        save.clicked.connect(self.save_network_identity)
        clear.clicked.connect(self.clear_network_identity)
        actions.addWidget(save)
        actions.addWidget(clear)
        actions.addStretch()
        layout.addLayout(actions)
        self.network_status = QLabel("Hazır")
        self.network_status.setWordWrap(True)
        layout.addWidget(self.network_status)
        layout.addStretch()
        return page

    def refresh_network_profiles(self):
        current = self.network_profile.currentText() if hasattr(self, "network_profile") else ""
        names = self.account_names() if hasattr(self, "account_names") else []
        self.network_profile.blockSignals(True)
        self.network_profile.clear()
        self.network_profile.addItems(names)
        if current in names:
            self.network_profile.setCurrentText(current)
        self.network_profile.blockSignals(False)
        self.load_network_identity(self.network_profile.currentText())

    def load_network_identity(self, profile):
        if not profile:
            self.network_server.clear(); self.network_username.clear(); self.network_password.clear()
            self.network_status.setText("Önce profil ekleyin")
            return
        identity = network_identity.load(profile)
        self.network_server.setText(identity.server)
        self.network_username.setText(identity.username)
        self.network_password.setText(identity.password)
        self.network_status.setText(
            f"{profile}: " + (f"sabit geçit {identity.server}" if identity.server else "doğrudan bağlantı")
        )

    def save_network_identity(self):
        profile = self.network_profile.currentText().strip()
        if not profile:
            QMessageBox.warning(self, "Profil yok", "Önce profil ekleyin.")
            return
        try:
            identity = network_identity.NetworkIdentity(
                self.network_server.text().strip(),
                self.network_username.text().strip(),
                self.network_password.text(),
            )
            network_identity.save(profile, identity)
            self.network_status.setText(f"{profile}: sabit ağ geçidi kaydedildi")
            QMessageBox.information(
                self, "Kaydedildi",
                "Bu profil sonraki Chrome açılışından itibaren aynı sabit ağ geçidini kullanacak.",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Ağ geçidi hatası", str(exc))

    def clear_network_identity(self):
        profile = self.network_profile.currentText().strip()
        if not profile:
            return
        network_identity.delete(profile)
        self.load_network_identity(profile)

    def build_ui(self):
        original_build(self)
        self.network_identity_page = network_tab(self)
        self.tabs.addTab(self.network_identity_page, "Sabit Profil Ağı")
        refresh_network_profiles(self)

    def refresh(self):
        original_refresh(self)
        if hasattr(self, "network_profile"):
            refresh_network_profiles(self)

    window_class.build_ui = build_ui
    window_class.refresh = refresh
    window_class.network_tab = network_tab
    window_class.refresh_network_profiles = refresh_network_profiles
    window_class.load_network_identity = load_network_identity
    window_class.save_network_identity = save_network_identity
    window_class.clear_network_identity = clear_network_identity
    window_class._network_identity_gui_installed = True
