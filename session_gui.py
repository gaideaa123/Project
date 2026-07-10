from __future__ import annotations

"""Direct Session ID controls for the Azure + Web profile table."""

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout,
)

import tiktok_login


def install(window_class) -> None:
    if getattr(window_class, "_session_gui_installed", False):
        return

    original_tab = window_class.azure_web_tab
    original_refresh = window_class.refresh_web_profiles

    def configure_table(table) -> None:
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(
            ["Seç", "Profil", "Giriş", "Session ID", "Durum", "İşlem"]
        )

    def azure_web_tab(self):
        page = original_tab(self)
        configure_table(self.web_profiles)
        return page

    def refresh_web_profiles(self):
        original_refresh(self)
        configure_table(self.web_profiles)
        for row in range(self.web_profiles.rowCount()):
            profile_item = self.web_profiles.item(row, 1)
            if profile_item is None:
                continue
            profile = profile_item.text()
            status_item = self.web_profiles.takeItem(row, 3)
            publish_button = self.web_profiles.cellWidget(row, 4)
            self.web_profiles.removeCellWidget(row, 4)

            session_button = QPushButton(
                "Session güncelle" if tiktok_login.load_session(profile) else "Session ekle"
            )
            session_button.setToolTip("Bu profile ait TikTok sessionid değerini güvenli kasada yönet")
            session_button.clicked.connect(
                lambda _=False, selected=profile: self.edit_tiktok_session(selected)
            )
            self.web_profiles.setCellWidget(row, 3, session_button)
            self.web_profiles.setItem(row, 4, status_item)
            if publish_button is not None:
                self.web_profiles.setCellWidget(row, 5, publish_button)

    def edit_tiktok_session(self, profile: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{profile}: TikTok Session ID")
        dialog.setMinimumWidth(580)
        layout = QVBoxLayout(dialog)
        info = QLabel(
            "Session ID parola kadar hassastır. Yalnız işletim sistemi güvenli kasasında "
            "tutulur ve sadece bu profile ait izole tarayıcı oturumuna eklenir."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        session = QLineEdit()
        session.setObjectName("tiktokSessionIdInput")
        session.setPlaceholderText("sessionid değeri veya sessionid=...;")
        session.setEchoMode(QLineEdit.Password)
        session.setClearButtonEnabled(True)
        layout.addWidget(session)

        row = QHBoxLayout()
        reveal = QPushButton("Göster")
        reveal.setCheckable(True)
        def toggle(checked: bool) -> None:
            session.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
            reveal.setText("Gizle" if checked else "Göster")
        reveal.toggled.connect(toggle)
        row.addWidget(reveal)
        row.addStretch()
        layout.addLayout(row)

        buttons = QDialogButtonBox()
        save = buttons.addButton("Session kaydet", QDialogButtonBox.AcceptRole)
        delete = buttons.addButton("Session sil", QDialogButtonBox.DestructiveRole)
        cancel = buttons.addButton(QDialogButtonBox.Cancel)
        save.clicked.connect(dialog.accept)
        delete.clicked.connect(lambda: dialog.done(2))
        cancel.clicked.connect(dialog.reject)
        layout.addWidget(buttons)

        result = dialog.exec()
        try:
            if result == QDialog.Accepted:
                tiktok_login.save_session(profile, session.text())
                QMessageBox.information(self, "Kaydedildi", f"{profile} Session ID kaydedildi.")
            elif result == 2:
                tiktok_login.delete_session(profile)
                QMessageBox.information(self, "Silindi", f"{profile} Session ID silindi.")
            else:
                return
            self.refresh_web_profiles()
        except Exception as exc:
            QMessageBox.critical(self, "Session işlemi başarısız", str(exc))

    def mark_done(self, profile: str) -> None:
        for row in range(self.web_profiles.rowCount()):
            item = self.web_profiles.item(row, 1)
            if item is not None and item.text() == profile:
                status = self.web_profiles.item(row, 4)
                if status is not None:
                    status.setText("Yayınlandı")

    window_class.azure_web_tab = azure_web_tab
    window_class.refresh_web_profiles = refresh_web_profiles
    window_class.edit_tiktok_session = edit_tiktok_session
    window_class.mark_done = mark_done
    window_class._session_gui_installed = True
