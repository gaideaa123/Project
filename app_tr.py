from __future__ import annotations

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
import tiktok_login
import web_uploader

tiktok_login.install(web_uploader)
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
        self.key, self.url = key.strip(), url.strip()
        self.guide = guide.strip() or DEFAULT_GUIDE
        if not self.key:
            raise RuntimeError("Azure GPT API anahtarı boş")
        if not self.url.startswith("https://") or "/chat/completions" not in self.url:
            raise RuntimeError("Azure chat/completions URL geçersiz")

    def create(self, profile: str) -> str:
        prompt = (
            "Yalnız TikTok başlığı/caption metnini döndür; markdown veya açıklama ekleme.\n"
            f"Profil: {profile}\nKurallar: {self.guide}\n"
            f"Çeşitlilik anahtarı: {random.SystemRandom().randrange(10**12)}"
        )
        last_error = "Bilinmeyen Azure hatası"
        for attempt in range(3):
            try:
                response = requests.post(
                    self.url,
                    headers={"api-key": self.key, "Content-Type": "application/json"},
                    json={"temperature": 0.75 + attempt * 0.05, "messages": [
                        {"role": "system", "content": "Kıdemli Türkçe sosyal medya editörüsün."},
                        {"role": "user", "content": prompt},
                    ]}, timeout=(15, 90),
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
                if not caption or len(caption) > 2200 or not re.search(r"\w", caption, re.UNICODE):
                    raise RuntimeError("Azure kullanılabilir uzunlukta bir başlık döndürmedi")
                return caption
            except (requests.RequestException, KeyError, IndexError, TypeError, RuntimeError) as exc:
                last_error = str(exc)
        raise RuntimeError(f"Azure başlık üretemedi: {last_error}")


class PublishWorker(QThread):
    status = Signal(str); preview_ready = Signal(str, str, str)
    profile_done = Signal(str); all_done = Signal(int); failed = Signal(str)

    def __init__(self, profiles, video, key, url, guide, parent=None):
        super().__init__(parent); self.profiles, self.video = profiles, video
        self.key, self.url, self.guide = key, url, guide
        self._decision = threading.Event(); self._approved = False; self._cancelled = False

    def decide(self, approved): self._approved = approved; self._decision.set()
    def cancel(self): self._cancelled = True; self.decide(False)
    def _approval(self, profile, caption):
        self._approved = False; self._decision.clear()
        self.preview_ready.emit(profile, str(self.video), caption); self._decision.wait()
        return self._approved and not self._cancelled

    def run(self):
        completed = 0
        try:
            client = AzureTitleClient(self.key, self.url, self.guide)
            for profile in self.profiles:
                if self._cancelled: break
                self.status.emit(f"{profile}: Azure GPT başlık oluşturuyor")
                caption = client.create(profile)
                web_uploader.prepare_upload(
                    web_uploader.UploadRequest(profile, self.video, caption), publish=True,
                    approval=lambda p=profile, c=caption: self._approval(p, c),
                    status=self.status.emit,
                )
                completed += 1; self.profile_done.emit(profile)
            self.all_done.emit(completed)
        except web_uploader.UploadError as exc:
            if self._cancelled or "iptal" in str(exc).casefold(): self.all_done.emit(completed)
            else: self.failed.emit(str(exc))
        except Exception as exc: self.failed.emit(str(exc))


class TurkceAnaPencere(core.MainWindow):
    def __init__(self):
        self.publish_worker = None; super().__init__()
        self.setWindowTitle("SignalDesk: Azure + Web Yayıncı")

    def build_ui(self):
        super().build_ui(); self.tabs.insertTab(1, self.azure_web_tab(), "Azure + Web Yükleyici")

    def azure_web_tab(self):
        page = QWidget(); layout = QVBoxLayout(page)
        note = QLabel("Profil seç: Azure GPT başlık üretir, kayıtlı TikTok oturumuyla web yükleyiciyi açar. CAPTCHA/2FA çıkarsa tarayıcıda sen tamamlarsın.")
        note.setWordWrap(True); layout.addWidget(note)
        settings = QFormLayout()
        self.azure_key = QLineEdit(secret("api_key")); self.azure_key.setEchoMode(QLineEdit.Password)
        self.azure_url = QLineEdit(secret("api_url")); self.azure_guide = QLineEdit(secret("guide", DEFAULT_GUIDE))
        settings.addRow("Azure API Key", self.azure_key); settings.addRow("Azure chat/completions URL", self.azure_url)
        settings.addRow("Başlık kuralları", self.azure_guide); layout.addLayout(settings)
        media = QHBoxLayout(); self.web_video = QLineEdit(); self.web_video.setPlaceholderText("Yüklenecek video")
        choose = QPushButton("Video seç"); choose.clicked.connect(self.choose_web_video)
        media.addWidget(self.web_video, 1); media.addWidget(choose); layout.addLayout(media)
        controls = QHBoxLayout()
        save = QPushButton("Azure ayarlarını kaydet"); save.clicked.connect(self.save_azure)
        select_all = QPushButton("Tümünü seç"); select_all.clicked.connect(self.select_all_profiles)
        publish_all = QPushButton("SEÇİLENLERİ AZURE + WEB İLE YAYINLA"); publish_all.clicked.connect(self.publish_selected)
        self.cancel_publish = QPushButton("İptal"); self.cancel_publish.setEnabled(False); self.cancel_publish.clicked.connect(self.cancel_current)
        for button in (save, select_all, publish_all, self.cancel_publish): controls.addWidget(button)
        layout.addLayout(controls)
        self.web_profiles = QTableWidget(0, 5)
        self.web_profiles.setHorizontalHeaderLabels(["Seç", "Profil", "Giriş", "Durum", "İşlem"])
        self.web_profiles.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.web_profiles.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.web_profiles); self.web_status = QLabel("Hazır"); layout.addWidget(self.web_status)
        return page

    def refresh(self):
        super().refresh()
        if hasattr(self, "web_profiles") and self.publish_worker is None: self.refresh_web_profiles()

    def refresh_web_profiles(self):
        accounts = self.registry.snapshot().get("accounts", []); self.web_profiles.setRowCount(len(accounts))
        for row, account in enumerate(accounts):
            name = str(account.get("name") or account.get("profile_name") or "TikTok")
            self.web_profiles.setCellWidget(row, 0, QCheckBox()); self.web_profiles.setItem(row, 1, QTableWidgetItem(name))
            login = QPushButton("Girişi güncelle" if tiktok_login.has_credentials(name) else "Giriş kaydet")
            login.clicked.connect(lambda _=False, profile=name: self.save_tiktok_login(profile))
            self.web_profiles.setCellWidget(row, 2, login); self.web_profiles.setItem(row, 3, QTableWidgetItem("Hazır"))
            publish = QPushButton("Azure + Web ile yayınla")
            publish.clicked.connect(lambda _=False, profile=name: self.publish_profiles([profile]))
            self.web_profiles.setCellWidget(row, 4, publish)

    def save_tiktok_login(self, profile):
        dialog = QMessageBox(self); dialog.setWindowTitle(f"{profile}: TikTok girişini kaydet")
        dialog.setText("Bilgiler yalnız işletim sistemi güvenli kasasında tutulur. CAPTCHA ve 2FA otomatik geçilmez.")
        identity = QLineEdit(); identity.setPlaceholderText("Kullanıcı adı, e-posta veya telefon")
        password = QLineEdit(); password.setPlaceholderText("TikTok parolası"); password.setEchoMode(QLineEdit.Password)
        dialog.layout().addWidget(identity, 1, 1); dialog.layout().addWidget(password, 2, 1)
        dialog.setStandardButtons(QMessageBox.Save | QMessageBox.Cancel)
        if dialog.exec() != QMessageBox.Save: return
        try:
            tiktok_login.save_credentials(profile, identity.text(), password.text())
            QMessageBox.information(self, "Kaydedildi", "TikTok girişi güvenli kasaya kaydedildi.")
            self.refresh_web_profiles()
        except Exception as exc: QMessageBox.critical(self, "Giriş kaydedilemedi", str(exc))

    def choose_web_video(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Yüklenecek videoyu seç", "", "Video (*.mp4 *.mov *.m4v *.webm)")
        if filename: self.web_video.setText(str(Path(filename).resolve()))

    def save_azure(self, show_message=True):
        values = {"api_key": self.azure_key.text().strip(), "api_url": self.azure_url.text().strip(), "guide": self.azure_guide.text().strip() or DEFAULT_GUIDE}
        try:
            AzureTitleClient(values["api_key"], values["api_url"], values["guide"])
            for name, value in values.items(): keyring.set_password(AZURE_SERVICE, name, value)
            if show_message: QMessageBox.information(self, "Kaydedildi", "Azure ayarları güvenli kasaya kaydedildi.")
            return True
        except Exception as exc: QMessageBox.critical(self, "Azure ayarı hatalı", str(exc)); return False

    def select_all_profiles(self):
        for row in range(self.web_profiles.rowCount()):
            box = self.web_profiles.cellWidget(row, 0)
            if isinstance(box, QCheckBox): box.setChecked(True)

    def publish_selected(self):
        profiles = []
        for row in range(self.web_profiles.rowCount()):
            box, item = self.web_profiles.cellWidget(row, 0), self.web_profiles.item(row, 1)
            if isinstance(box, QCheckBox) and box.isChecked() and item: profiles.append(item.text())
        self.publish_profiles(profiles)

    def publish_profiles(self, profiles):
        if self.publish_worker is not None: QMessageBox.warning(self, "Yayın sürüyor", "Önce çalışan akışı tamamlayın."); return
        if not profiles: QMessageBox.warning(self, "Profil seçilmedi", "En az bir profil seçin."); return
        video = Path(self.web_video.text().strip()).expanduser()
        try: web_uploader.UploadRequest(profiles[0], video, "doğrulama").validate()
        except Exception as exc: QMessageBox.warning(self, "Video hatası", str(exc)); return
        if not self.save_azure(False): return
        worker = PublishWorker(profiles, video.resolve(), self.azure_key.text(), self.azure_url.text(), self.azure_guide.text(), self)
        self.publish_worker = worker; worker.status.connect(self.web_status.setText)
        worker.preview_ready.connect(self.confirm_preview); worker.profile_done.connect(self.mark_done)
        worker.failed.connect(self.publish_failed); worker.all_done.connect(self.publish_finished)
        worker.finished.connect(self.cleanup_worker); self.cancel_publish.setEnabled(True); worker.start()

    def confirm_preview(self, profile, video, caption):
        answer = QMessageBox.question(self, f"{profile}: son yayın onayı", f"Tarayıcı önizlemesini kontrol et.\n\nVideo: {video}\n\nBaşlık:\n{caption}\n\nYayınlansın mı?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if self.publish_worker: self.publish_worker.decide(answer == QMessageBox.Yes)

    def mark_done(self, profile):
        for row in range(self.web_profiles.rowCount()):
            if self.web_profiles.item(row, 1) and self.web_profiles.item(row, 1).text() == profile: self.web_profiles.item(row, 3).setText("Yayınlandı")

    def cancel_current(self):
        if self.publish_worker: self.publish_worker.cancel(); self.web_status.setText("İptal ediliyor")
    def publish_failed(self, detail): self.web_status.setText("Başarısız"); QMessageBox.critical(self, "Azure + Web yayın hatası", detail)
    def publish_finished(self, count):
        self.web_status.setText(f"Tamamlandı: {count} profil")
        if count: QMessageBox.information(self, "Yayın tamamlandı", f"{count} profil başarıyla işlendi.")
    def cleanup_worker(self):
        worker = self.publish_worker; self.publish_worker = None; self.cancel_publish.setEnabled(False)
        if worker: worker.deleteLater()
    def closeEvent(self, event):
        if self.publish_worker: self.publish_worker.cancel(); self.publish_worker.wait(5000)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv); app.setApplicationName("SignalDesk Azure + Web"); app.setOrganizationName("SignalDesk"); app.setStyle("Fusion")
    QLocale.setDefault(QLocale(QLocale.Turkish, QLocale.Turkey)); window = TurkceAnaPencere(); window.show(); return app.exec()


if __name__ == "__main__": raise SystemExit(main())
