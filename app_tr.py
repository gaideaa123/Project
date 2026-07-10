from __future__ import annotations

import json
import os
import random
import re
import sys
import threading
from pathlib import Path

import keyring
import requests
from PySide6.QtCore import QLocale, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import app as core
import web_uploader

AZURE_SERVICE = "signaldesk-azure-gpt4o"
DEFAULT_GUIDE = (
    "Türkiye Türkçesiyle doğal ve merak uyandıran iki kısa cümle yaz. "
    "Abartılı vaat kullanma. İkinci satıra tam 5 alakalı hashtag ekle."
)


def secret(name: str, default: str = "") -> str:
    try:
        return keyring.get_password(AZURE_SERVICE, name) or default
    except Exception:
        return default


class AzureTitleClient:
    def __init__(self, key: str, url: str, guide: str):
        self.key = key.strip()
        self.url = url.strip()
        self.guide = guide.strip() or DEFAULT_GUIDE
        if not self.key:
            raise RuntimeError("Azure GPT API anahtarı boş")
        if not self.url.startswith("https://") or "/chat/completions" not in self.url:
            raise RuntimeError("Azure chat/completions URL geçersiz")

    def create(self, profile: str) -> str:
        prompt = (
            "Yalnızca TikTok başlığı/caption metnini döndür. Markdown veya açıklama ekleme.\n"
            f"Profil: {profile}\nKurallar: {self.guide}\n"
            f"Çeşitlilik anahtarı: {random.SystemRandom().randrange(10**12)}"
        )
        last_error = "Bilinmeyen Azure hatası"
        for attempt in range(3):
            try:
                response = requests.post(
                    self.url,
                    headers={"api-key": self.key, "Content-Type": "application/json"},
                    json={
                        "temperature": 0.75 + attempt * 0.05,
                        "messages": [
                            {"role": "system", "content": "Kıdemli Türkçe sosyal medya editörüsün."},
                            {"role": "user", "content": prompt},
                        ],
                    },
                    timeout=(15, 90),
                )
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise RuntimeError(f"Azure geçersiz JSON döndürdü: HTTP {response.status_code}") from exc
                if not response.ok:
                    error = payload.get("error", {})
                    detail = error.get("message") if isinstance(error, dict) else str(error)
                    raise RuntimeError(detail or f"Azure HTTP {response.status_code}")
                caption = str(payload["choices"][0]["message"]["content"]).strip().strip('"')
                if not caption or len(caption) > 2200:
                    raise RuntimeError("Azure boş veya 2200 karakterden uzun metin döndürdü")
                if not re.search(r"\w", caption, re.UNICODE):
                    raise RuntimeError("Azure kullanılabilir bir başlık döndürmedi")
                return caption
            except (requests.RequestException, KeyError, IndexError, TypeError, RuntimeError) as exc:
                last_error = str(exc)
        raise RuntimeError(f"Azure başlık üretemedi: {last_error}")


class PublishWorker(QThread):
    status = Signal(str)
    preview_ready = Signal(str, str, str)
    profile_done = Signal(str)
    all_done = Signal(int)
    failed = Signal(str)

    def __init__(self, profiles: list[str], video: Path, key: str, url: str, guide: str, parent=None):
        super().__init__(parent)
        self.profiles = profiles
        self.video = video
        self.key = key
        self.url = url
        self.guide = guide
        self._decision = threading.Event()
        self._approved = False
        self._cancelled = False

    def decide(self, approved: bool) -> None:
        self._approved = approved
        self._decision.set()

    def cancel(self) -> None:
        self._cancelled = True
        self.decide(False)

    def _approval(self, profile: str, caption: str) -> bool:
        self._approved = False
        self._decision.clear()
        self.preview_ready.emit(profile, str(self.video), caption)
        self._decision.wait()
        return self._approved and not self._cancelled

    def run(self) -> None:
        completed = 0
        try:
            client = AzureTitleClient(self.key, self.url, self.guide)
            for profile in self.profiles:
                if self._cancelled:
                    break
                self.status.emit(f"{profile}: Azure GPT başlık oluşturuyor")
                caption = client.create(profile)
                self.status.emit(f"{profile}: görünür web yükleyici hazırlanıyor")
                web_uploader.prepare_upload(
                    web_uploader.UploadRequest(profile, self.video, caption),
                    publish=True,
                    approval=lambda p=profile, c=caption: self._approval(p, c),
                )
                completed += 1
                self.profile_done.emit(profile)
            self.all_done.emit(completed)
        except Exception as exc:
            self.failed.emit(str(exc))


class TurkceAnaPencere(core.MainWindow):
    def __init__(self):
        self.publish_worker: PublishWorker | None = None
        super().__init__()
        self.setWindowTitle("SignalDesk: Azure + Web Yayıncı")

    def build_ui(self) -> None:
        super().build_ui()
        self.tabs.insertTab(1, self.azure_web_tab(), "Azure + Web Yükleyici")

    def azure_web_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(
            "Bir profili veya tüm profilleri seç: Azure GPT başlığı oluşturur, görünür TikTok Studio "
            "oturumunu açar ve sen önizlemeyi onayladıktan sonra Yayınla düğmesine basar."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        settings = QFormLayout()
        self.azure_key = QLineEdit(secret("api_key"))
        self.azure_key.setEchoMode(QLineEdit.Password)
        self.azure_url = QLineEdit(secret("api_url"))
        self.azure_guide = QLineEdit(secret("guide", DEFAULT_GUIDE))
        settings.addRow("Azure API Key", self.azure_key)
        settings.addRow("Azure chat/completions URL", self.azure_url)
        settings.addRow("Başlık kuralları", self.azure_guide)
        layout.addLayout(settings)

        media_row = QHBoxLayout()
        self.web_video = QLineEdit()
        self.web_video.setPlaceholderText("Yüklenecek video")
        choose = QPushButton("Video seç")
        choose.clicked.connect(self.choose_web_video)
        media_row.addWidget(self.web_video, 1)
        media_row.addWidget(choose)
        layout.addLayout(media_row)

        controls = QHBoxLayout()
        save = QPushButton("Azure ayarlarını kaydet")
        save.clicked.connect(self.save_azure)
        select_all = QPushButton("Tümünü seç")
        select_all.clicked.connect(self.select_all_profiles)
        publish_all = QPushButton("SEÇİLENLERİ AZURE + WEB İLE YAYINLA")
        publish_all.clicked.connect(self.publish_selected)
        self.cancel_publish = QPushButton("İptal")
        self.cancel_publish.setEnabled(False)
        self.cancel_publish.clicked.connect(self.cancel_current)
        controls.addWidget(save)
        controls.addWidget(select_all)
        controls.addWidget(publish_all)
        controls.addWidget(self.cancel_publish)
        layout.addLayout(controls)

        self.web_profiles = QTableWidget(0, 4)
        self.web_profiles.setHorizontalHeaderLabels(["Seç", "Profil", "Durum", "İşlem"])
        self.web_profiles.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.web_profiles.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.web_profiles)
        self.web_status = QLabel("Hazır")
        layout.addWidget(self.web_status)
        return page

    def refresh(self) -> None:
        super().refresh()
        if hasattr(self, "web_profiles") and self.publish_worker is None:
            self.refresh_web_profiles()

    def refresh_web_profiles(self) -> None:
        accounts = self.registry.snapshot().get("accounts", [])
        self.web_profiles.setRowCount(len(accounts))
        for row, account in enumerate(accounts):
            name = str(account.get("name") or account.get("profile_name") or "TikTok")
            box = QCheckBox()
            self.web_profiles.setCellWidget(row, 0, box)
            self.web_profiles.setItem(row, 1, QTableWidgetItem(name))
            self.web_profiles.setItem(row, 2, QTableWidgetItem("Hazır"))
            button = QPushButton("Azure + Web ile yayınla")
            button.clicked.connect(lambda _=False, profile=name: self.publish_profiles([profile]))
            self.web_profiles.setCellWidget(row, 3, button)

    def choose_web_video(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Yüklenecek videoyu seç", "", "Video (*.mp4 *.mov *.m4v *.webm)"
        )
        if filename:
            self.web_video.setText(str(Path(filename).resolve()))

    def save_azure(self, show_message: bool = True) -> bool:
        values = {
            "api_key": self.azure_key.text().strip(),
            "api_url": self.azure_url.text().strip(),
            "guide": self.azure_guide.text().strip() or DEFAULT_GUIDE,
        }
        try:
            AzureTitleClient(values["api_key"], values["api_url"], values["guide"])
            for name, value in values.items():
                keyring.set_password(AZURE_SERVICE, name, value)
            if show_message:
                QMessageBox.information(self, "Kaydedildi", "Azure ayarları işletim sistemi kasasına kaydedildi.")
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Azure ayarı hatalı", str(exc))
            return False

    def select_all_profiles(self) -> None:
        for row in range(self.web_profiles.rowCount()):
            box = self.web_profiles.cellWidget(row, 0)
            if isinstance(box, QCheckBox):
                box.setChecked(True)

    def publish_selected(self) -> None:
        profiles = []
        for row in range(self.web_profiles.rowCount()):
            box = self.web_profiles.cellWidget(row, 0)
            item = self.web_profiles.item(row, 1)
            if isinstance(box, QCheckBox) and box.isChecked() and item:
                profiles.append(item.text())
        self.publish_profiles(profiles)

    def publish_profiles(self, profiles: list[str]) -> None:
        if self.publish_worker is not None:
            QMessageBox.warning(self, "Yayın sürüyor", "Önce çalışan yayın akışını tamamlayın veya iptal edin.")
            return
        if not profiles:
            QMessageBox.warning(self, "Profil seçilmedi", "En az bir profil seçin.")
            return
        video = Path(self.web_video.text().strip()).expanduser()
        try:
            web_uploader.UploadRequest(profiles[0], video, "doğrulama").validate()
        except Exception as exc:
            QMessageBox.warning(self, "Video hatası", str(exc))
            return
        if not self.save_azure(False):
            return
        self.publish_worker = PublishWorker(
            profiles, video.resolve(), self.azure_key.text(), self.azure_url.text(),
            self.azure_guide.text(), self,
        )
        self.publish_worker.status.connect(self.web_status.setText)
        self.publish_worker.preview_ready.connect(self.confirm_preview)
        self.publish_worker.profile_done.connect(self.mark_done)
        self.publish_worker.failed.connect(self.publish_failed)
        self.publish_worker.all_done.connect(self.publish_finished)
        self.cancel_publish.setEnabled(True)
        self.publish_worker.start()

    def confirm_preview(self, profile: str, video: str, caption: str) -> None:
        answer = QMessageBox.question(
            self,
            f"{profile}: son yayın onayı",
            f"Tarayıcıdaki önizlemeyi kontrol et.\n\nVideo: {video}\n\nBaşlık:\n{caption}\n\n"
            "Şimdi TikTok'taki Yayınla düğmesine basılsın mı?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if self.publish_worker:
            self.publish_worker.decide(answer == QMessageBox.Yes)

    def mark_done(self, profile: str) -> None:
        for row in range(self.web_profiles.rowCount()):
            if self.web_profiles.item(row, 1) and self.web_profiles.item(row, 1).text() == profile:
                self.web_profiles.item(row, 2).setText("Yayınlandı")

    def cancel_current(self) -> None:
        if self.publish_worker:
            self.publish_worker.cancel()
            self.web_status.setText("İptal ediliyor")

    def publish_failed(self, detail: str) -> None:
        QMessageBox.critical(self, "Azure + Web yayın hatası", detail)
        self.web_status.setText("Başarısız")
        self.cleanup_worker()

    def publish_finished(self, count: int) -> None:
        self.web_status.setText(f"Tamamlandı: {count} profil")
        if count:
            QMessageBox.information(self, "Yayın tamamlandı", f"{count} profil başarıyla işlendi.")
        self.cleanup_worker()

    def cleanup_worker(self) -> None:
        worker = self.publish_worker
        self.publish_worker = None
        self.cancel_publish.setEnabled(False)
        if worker:
            worker.deleteLater()

    def closeEvent(self, event) -> None:
        if self.publish_worker:
            self.publish_worker.cancel()
            self.publish_worker.wait(5000)
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("SignalDesk Azure + Web")
    app.setOrganizationName("SignalDesk")
    app.setStyle("Fusion")
    QLocale.setDefault(QLocale(QLocale.Turkish, QLocale.Turkey))
    window = TurkceAnaPencere()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
