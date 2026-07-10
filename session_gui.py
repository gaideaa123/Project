from __future__ import annotations

"""Session ID controls installed into the existing profile GUI."""

from PySide6.QtWidgets import QLineEdit, QMessageBox, QPushButton

import tiktok_login


def install(window_class) -> None:
    if getattr(window_class, "_session_gui_installed", False):
        return

    original_tab = window_class.azure_web_tab
    original_refresh = window_class.refresh_web_profiles

    def azure_web_tab(self):
        page = original_tab(self)
        self.web_profiles.setColumnCount(6)
        self.web_profiles.setHorizontalHeaderLabels(
            ["Seç", "Profil", "Giriş", "Session ID", "Durum", "İşlem"]
        )
        return page

    def refresh_web_profiles(self):
        original_refresh(self)
        self.web_profiles.setColumnCount(6)
        self.web_profiles.setHorizontalHeaderLabels(
            ["Seç", "Profil", "Giriş", "Session ID", "Durum", "İşlem"]
        )
        for row in range(self.web_profiles.rowCount()):
            profile_item = self.web_profiles.item(row, 1)
            if not profile_item:
                continue
            profile = profile_item.text()
            old_status = self.web_profiles.takeItem(row, 3)
            old_publish = self.web_profiles.cellWidget(row, 4)
            self.web_profiles.removeCellWidget(row, 4)

            session_button = QPushButton(
                "Session güncelle" if tiktok_login.load_session(profile) else "Session ekle"
            )
            session_button.clicked.connect(
                lambda _=False, selected=profile: self.edit_tiktok_session(selected)
            )
            self.web_profiles.setCellWidget(row, 3, session_button)
            self.web_profiles.setItem(row, 4, old_status)
            if old_publish:
                self.web_profiles.setCellWidget(row, 5, old_publish)

    def edit_tiktok_session(self, profile: str) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle(f"{profile}: TikTok Session ID")
        dialog.setText(
            "Bu değer parola kadar hassastır ve yalnız işletim sistemi güvenli kasasında tutulur. "
            "sessionid değerini veya tam sessionid=...; metnini yapıştırın."
        )
        session = QLineEdit()
        session.setPlaceholderText("sessionid")
        session.setEchoMode(QLineEdit.Password)
        session.setClearButtonEnabled(True)
        show = QPushButton("Göster / gizle")
        show.clicked.connect(
            lambda: session.setEchoMode(
                QLineEdit.Normal if session.echoMode() == QLineEdit.Password else QLineEdit.Password
            )
        )
        dialog.layout().addWidget(session, 1, 1)
        dialog.layout().addWidget(show, 2, 1)
        dialog.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        dialog.button(QMessageBox.Save).setText("Session kaydet")
        dialog.button(QMessageBox.Discard).setText("Session sil")
        result = dialog.exec()
        try:
            if result == QMessageBox.Save:
                tiktok_login.save_session(profile, session.text())
                QMessageBox.information(
                    self, "Kaydedildi", f"{profile} session ID güvenli kasaya kaydedildi."
                )
            elif result == QMessageBox.Discard:
                tiktok_login.delete_session(profile)
                QMessageBox.information(self, "Silindi", f"{profile} session ID silindi.")
            else:
                return
            self.refresh_web_profiles()
        except Exception as exc:
            QMessageBox.critical(self, "Session kaydedilemedi", str(exc))

    original_mark_done = window_class.mark_done

    def mark_done(self, profile):
        original_mark_done(self, profile)
        for row in range(self.web_profiles.rowCount()):
            item = self.web_profiles.item(row, 1)
            if item and item.text() == profile:
                status = self.web_profiles.item(row, 4)
                if status:
                    status.setText("Yayınlandı")

    window_class.azure_web_tab = azure_web_tab
    window_class.refresh_web_profiles = refresh_web_profiles
    window_class.edit_tiktok_session = edit_tiktok_session
    window_class.mark_done = mark_done
    window_class._session_gui_installed = True
