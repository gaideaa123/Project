from __future__ import annotations

import logging
import random
import re
import sys
import threading
from pathlib import Path

import keyring
import requests
from platformdirs import user_data_dir
from PySide6.QtCore import QLocale, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import app as core
import tiktok_login
import video_variants
import web_uploader
from uniquizer_tab import UniquizerTab

AZURE_SERVICE = "signaldesk-azure-gpt4o"
GUIDE = """Konu: Başlık üretmeyi kolaylaştıran faydalı bir internet sitesi.
Ton: doğal, merak uyandıran, enerjik, samimi ve güvenilir.
Biçim: iki kısa cümle, 2-4 doğal emoji, ikinci satırda tam 5 alakalı hashtag.
Dil: kusursuz Türkiye Türkçesi; anlatım, yazım ve noktalama hatası olmasın.
Doğrulanmamış sonuç, garanti, sahte deneyim veya abartılı vaat yazma."""
LOG_DIR = Path(user_data_dir("signaldesk-studio", "SignalDesk")); LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=LOG_DIR / "app_tr_errors.log", level=logging.INFO)
LOGGER = logging.getLogger("signaldesk.app_tr")
tiktok_login.install(web_uploader)


def secret(name: str, default: str = "") -> str:
    try: return keyring.get_password(AZURE_SERVICE, name) or default
    except Exception: return default


class AzureTitleClient:
    def __init__(self, key: str, url: str, guide: str):
        self.key, self.url, self.guide = key.strip(), url.strip(), guide.strip() or GUIDE
        if not self.key: raise RuntimeError("Azure GPT API anahtarı boş")
        if not self.url.startswith("https://") or "/chat/completions" not in self.url:
            raise RuntimeError("Azure chat/completions URL geçersiz")

    def create(self, profile: str) -> str:
        prompt = f"""Türkçe TikTok captionu yaz. Yalnız sonucu döndür.
Rehber: {self.guide}
İlk satır iki kısa doğal cümle ve 2-4 emoji içersin. İkinci satır yalnız tam 5 hashtag olsun.
Dil bilgisi kusursuz olsun. Profil: {profile}
Çeşitlilik: {random.SystemRandom().randrange(10**12)}"""
        last_error = "Azure yanıt vermedi"
        for attempt in range(3):
            try:
                response = requests.post(
                    self.url, headers={"api-key": self.key, "Content-Type": "application/json"},
                    json={"temperature": .75 + attempt * .05, "messages": [
                        {"role": "system", "content": "Kıdemli Türkçe sosyal medya editörüsün."},
                        {"role": "user", "content": prompt},
                    ]}, timeout=(15, 90),
                )
                payload = response.json()
                if not response.ok:
                    error = payload.get("error", {})
                    raise RuntimeError(error.get("message") if isinstance(error, dict) else str(error))
                caption = str(payload["choices"][0]["message"]["content"]).strip().strip('"')
                if not caption or len(caption) > 2200 or not re.search(r"\w", caption):
                    raise RuntimeError("Azure geçerli caption döndürmedi")
                return caption
            except Exception as exc: last_error = str(exc)
        raise RuntimeError(f"Azure caption üretemedi: {last_error}")


class PublishWorker(QThread):
    status = Signal(str); progress = Signal(int); variants_ready = Signal(object)
    preview_ready = Signal(str, str, str); profile_done = Signal(str); all_done = Signal(int); failed = Signal(str)

    def __init__(self, profiles, source, variant_count, key, url, guide, parent=None):
        super().__init__(parent); self.profiles, self.source = profiles, source
        self.variant_count = variant_count; self.key, self.url, self.guide = key, url, guide
        self._decision = threading.Event(); self._approved = False; self._cancelled = False

    def decide(self, approved): self._approved = approved; self._decision.set()
    def cancel(self): self._cancelled = True; self.decide(False)
    def _approval(self, profile, video, caption):
        self._approved = False; self._decision.clear(); self.preview_ready.emit(profile, str(video), caption)
        self._decision.wait(); return self._approved and not self._cancelled

    def run(self):
        completed = 0
        try:
            self.status.emit(f"1.mp4 - {self.variant_count}.mp4 oluşturuluyor")
            variants = video_variants.create_variants(
                self.source, self.variant_count,
                lambda percent, text: (self.progress.emit(percent), self.status.emit(text)),
                cold_open=True,
            )
            self.variants_ready.emit([str(path) for path in variants])
            client = AzureTitleClient(self.key, self.url, self.guide)
            for index, profile in enumerate(self.profiles):
                if self._cancelled: break
                video = variants[index % len(variants)]
                self.status.emit(f"{profile}: {video.name} ve Azure caption hazırlanıyor")
                caption = client.create(profile)
                web_uploader.prepare_upload(
                    web_uploader.UploadRequest(profile, video, caption), publish=True,
                    approval=lambda p=profile, v=video, c=caption: self._approval(p, v, c),
                    status=self.status.emit,
                )
                completed += 1; self.profile_done.emit(profile)
            self.all_done.emit(completed)
        except Exception as exc:
            LOGGER.exception("Publish worker failed")
            if self._cancelled or "iptal" in str(exc).casefold(): self.all_done.emit(completed)
            else: self.failed.emit(str(exc))


class TurkceAnaPencere(core.MainWindow):
    def __init__(self):
        self.publish_worker = None
        self.uniquizer_tab: UniquizerTab | None = None
        super().__init__()
        self.setWindowTitle("SignalDesk: Azure + Web Yayıncı")

    def build_ui(self):
        super().build_ui()
        self.uniquizer_tab = UniquizerTab(self)
        self.tabs.insertTab(1, self.uniquizer_tab, "Varyasyonlara Ayır")
        self.tabs.insertTab(2, self.azure_web_tab(), "Azure + Web Yükleyici")

    def azure_web_tab(self):
        page = QWidget(); layout = QVBoxLayout(page)
        note = QLabel("Varyasyon sayısını gir: dosyalar 1.mp4, 2.mp4, 3.mp4... olarak oluşturulur ve seçili hesaplara sırayla dağıtılır.")
        note.setWordWrap(True); layout.addWidget(note)
        settings = QFormLayout()
        self.azure_key = QLineEdit(secret("api_key")); self.azure_key.setEchoMode(QLineEdit.Password)
        self.azure_url = QLineEdit(secret("api_url")); self.azure_guide = QLineEdit(secret("guide", GUIDE))
        settings.addRow("Azure API Key", self.azure_key); settings.addRow("Azure URL", self.azure_url); settings.addRow("Guide", self.azure_guide)
        self.variant_count = QSpinBox(); self.variant_count.setRange(1, 100); self.variant_count.setValue(5); self.variant_count.setSuffix(" varyasyon")
        settings.addRow("Varyasyon sayısı", self.variant_count); layout.addLayout(settings)
        media = QHBoxLayout(); self.web_video = QLineEdit(); self.web_video.setPlaceholderText("Kaynak video")
        choose = QPushButton("Video seç"); choose.clicked.connect(self.choose_web_video)
        media.addWidget(self.web_video, 1); media.addWidget(choose); layout.addLayout(media)
        self.variant_progress = QProgressBar(); layout.addWidget(self.variant_progress)
        self.variant_folder = QLabel("Varyasyon klasörü: henüz oluşturulmadı"); self.variant_folder.setWordWrap(True); layout.addWidget(self.variant_folder)
        controls = QHBoxLayout()
        add_account = QPushButton("SESSION ID İLE YENİ HESAP EKLE"); add_account.clicked.connect(self.add_session_account)
        save = QPushButton("Azure ayarlarını kaydet"); save.clicked.connect(self.save_azure)
        select_all = QPushButton("Tümünü seç"); select_all.clicked.connect(self.select_all_profiles)
        publish = QPushButton("VARYASYONLARI OLUŞTUR + WEB İLE YAYINLA"); publish.clicked.connect(self.publish_selected)
        self.cancel_publish = QPushButton("İptal"); self.cancel_publish.setEnabled(False); self.cancel_publish.clicked.connect(self.cancel_current)
        for button in (add_account, save, select_all, publish, self.cancel_publish): controls.addWidget(button)
        layout.addLayout(controls)
        self.web_profiles = QTableWidget(0, 6); self.web_profiles.setHorizontalHeaderLabels(["Seç", "Profil", "Giriş", "Session ID", "Durum", "İşlem"])
        self.web_profiles.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch); self.web_profiles.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(self.web_profiles); self.web_status = QLabel("Hazır"); layout.addWidget(self.web_status); return page

    def refresh(self):
        super().refresh()
        if hasattr(self, "web_profiles") and self.publish_worker is None: self.refresh_web_profiles()

    def refresh_web_profiles(self):
        accounts = self.registry.snapshot().get("accounts", []); self.web_profiles.clearContents(); self.web_profiles.setRowCount(len(accounts))
        for row, account in enumerate(accounts):
            name = str(account.get("name") or account.get("profile_name") or "TikTok")
            self.web_profiles.setCellWidget(row, 0, QCheckBox()); self.web_profiles.setItem(row, 1, QTableWidgetItem(name))
            login = QPushButton("Girişi güncelle" if tiktok_login.has_credentials(name) else "Giriş kaydet"); login.clicked.connect(lambda _=False, p=name: self.save_tiktok_login(p)); self.web_profiles.setCellWidget(row, 2, login)
            session = QPushButton("Session güncelle" if tiktok_login.has_session(name) else "Session ekle"); session.clicked.connect(lambda _=False, p=name: self.edit_tiktok_session(p)); self.web_profiles.setCellWidget(row, 3, session)
            self.web_profiles.setItem(row, 4, QTableWidgetItem("Hazır"))
            action = QPushButton("Varyasyon + Web yayınla"); action.clicked.connect(lambda _=False, p=name: self.publish_profiles([p])); self.web_profiles.setCellWidget(row, 5, action)

    def add_session_account(self):
        dialog = QDialog(self); dialog.setWindowTitle("Session ID ile yeni TikTok hesabı"); layout = QFormLayout(dialog)
        profile = QLineEdit(); profile.setPlaceholderText("Profil adı")
        session = QLineEdit(); session.setPlaceholderText("sessionid veya sessionid=...;"); session.setEchoMode(QLineEdit.Password)
        show = QCheckBox("Session ID'yi göster"); show.toggled.connect(lambda checked: session.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password))
        layout.addRow("Profil adı", profile); layout.addRow("Session ID", session); layout.addRow("", show)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addRow(buttons)
        if dialog.exec() != QDialog.Accepted: return
        name = profile.text().strip()
        try:
            if not name: raise RuntimeError("Profil adı boş olamaz")
            tiktok_login._session_value(session.text())
            account = self.registry.add_account(name)
            try: tiktok_login.save_session(name, session.text())
            except Exception:
                self.registry.delete_account(account["id"]); raise
            self.refresh(); self.tabs.setCurrentWidget(self.uniquizer_tab)
            QMessageBox.information(self, "Hesap eklendi", f"{name} Session ID ile eklendi.")
        except Exception as exc: QMessageBox.critical(self, "Hesap eklenemedi", str(exc))

    def edit_tiktok_session(self, profile):
        dialog = QDialog(self); dialog.setWindowTitle(f"{profile}: TikTok Session ID"); layout = QVBoxLayout(dialog)
        field = QLineEdit(); field.setPlaceholderText("sessionid veya sessionid=...;"); field.setEchoMode(QLineEdit.Password); layout.addWidget(field)
        show = QCheckBox("Göster"); show.toggled.connect(lambda checked: field.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)); layout.addWidget(show)
        buttons = QDialogButtonBox(); save = buttons.addButton("Kaydet", QDialogButtonBox.AcceptRole); delete = buttons.addButton("Sil", QDialogButtonBox.DestructiveRole); cancel = buttons.addButton(QDialogButtonBox.Cancel)
        save.clicked.connect(dialog.accept); delete.clicked.connect(lambda: dialog.done(2)); cancel.clicked.connect(dialog.reject); layout.addWidget(buttons)
        try:
            result = dialog.exec()
            if result == QDialog.Accepted: tiktok_login.save_session(profile, field.text())
            elif result == 2: tiktok_login.delete_session(profile)
            else: return
            self.refresh_web_profiles()
        except Exception as exc: QMessageBox.critical(self, "Session hatası", str(exc))

    def save_tiktok_login(self, profile):
        dialog = QDialog(self); dialog.setWindowTitle(f"{profile}: TikTok girişi"); layout = QFormLayout(dialog)
        identity, password = QLineEdit(), QLineEdit(); password.setEchoMode(QLineEdit.Password); layout.addRow("Hesap", identity); layout.addRow("Parola", password)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addRow(buttons)
        if dialog.exec() == QDialog.Accepted:
            try: tiktok_login.save_credentials(profile, identity.text(), password.text()); self.refresh_web_profiles()
            except Exception as exc: QMessageBox.critical(self, "Giriş hatası", str(exc))

    def choose_web_video(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Kaynak video", "", "Video (*.mp4 *.mov *.m4v *.webm *.mkv)")
        if filename: self.web_video.setText(str(Path(filename).resolve()))

    def save_azure(self, show_message=True):
        try:
            AzureTitleClient(self.azure_key.text(), self.azure_url.text(), self.azure_guide.text())
            for key, value in {"api_key":self.azure_key.text().strip(), "api_url":self.azure_url.text().strip(), "guide":self.azure_guide.text()}.items(): keyring.set_password(AZURE_SERVICE, key, value)
            if show_message: QMessageBox.information(self, "Kaydedildi", "Azure ayarları kaydedildi")
            return True
        except Exception as exc: QMessageBox.critical(self, "Azure hatası", str(exc)); return False

    def select_all_profiles(self):
        for row in range(self.web_profiles.rowCount()):
            box = self.web_profiles.cellWidget(row, 0)
            if isinstance(box, QCheckBox): box.setChecked(True)

    def publish_selected(self):
        profiles = [self.web_profiles.item(r, 1).text() for r in range(self.web_profiles.rowCount()) if isinstance(self.web_profiles.cellWidget(r, 0), QCheckBox) and self.web_profiles.cellWidget(r, 0).isChecked()]
        self.publish_profiles(profiles)

    def publish_profiles(self, profiles):
        try:
            if self.publish_worker: raise RuntimeError("Bir yayın akışı zaten çalışıyor")
            if not profiles: raise RuntimeError("En az bir profil seçin")
            source = Path(self.web_video.text().strip()).expanduser().resolve()
            if not source.is_file(): raise RuntimeError("Geçerli kaynak video seçin")
            if not self.save_azure(False): return
            worker = PublishWorker(profiles, source, self.variant_count.value(), self.azure_key.text(), self.azure_url.text(), self.azure_guide.text(), self)
            self.publish_worker = worker; worker.status.connect(self.web_status.setText); worker.progress.connect(self.variant_progress.setValue)
            worker.variants_ready.connect(self.show_variants); worker.preview_ready.connect(self.confirm_preview); worker.profile_done.connect(self.mark_done)
            worker.failed.connect(self.publish_failed); worker.all_done.connect(self.publish_finished); worker.finished.connect(self.cleanup_worker)
            self.cancel_publish.setEnabled(True); worker.start()
        except Exception as exc: QMessageBox.critical(self, "Yayın başlatılamadı", str(exc))

    def show_variants(self, paths):
        self.variant_folder.setText(f"Varyasyon klasörü: {Path(paths[0]).parent} | Dosyalar: 1.mp4 - {len(paths)}.mp4")

    def confirm_preview(self, profile, video, caption):
        answer = QMessageBox.question(self, f"{profile}: son onay", f"Video: {video}\n\nCaption:\n{caption}\n\nYayınlansın mı?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if self.publish_worker: self.publish_worker.decide(answer == QMessageBox.Yes)

    def mark_done(self, profile):
        for row in range(self.web_profiles.rowCount()):
            if self.web_profiles.item(row, 1).text() == profile: self.web_profiles.item(row, 4).setText("Yayınlandı")
    def cancel_current(self):
        if self.publish_worker: self.publish_worker.cancel(); self.web_status.setText("İptal ediliyor")
    def publish_failed(self, detail): self.web_status.setText("Başarısız"); QMessageBox.critical(self, "Yayın hatası", detail)
    def publish_finished(self, count): self.web_status.setText(f"Tamamlandı: {count} profil")
    def cleanup_worker(self):
        worker = self.publish_worker; self.publish_worker = None; self.cancel_publish.setEnabled(False)
        if worker: worker.deleteLater()
    def closeEvent(self, event):
        if self.uniquizer_tab and not self.uniquizer_tab.shutdown(5000):
            QMessageBox.warning(self, "Uniquizer çalışıyor", "Video üretimi bitmeden pencere kapatılamaz.")
            event.ignore(); return
        if self.publish_worker and self.publish_worker.isRunning():
            self.publish_worker.cancel()
            if not self.publish_worker.wait(5000): event.ignore(); return
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv); app.setApplicationName("SignalDesk Azure + Web"); app.setOrganizationName("SignalDesk"); app.setStyle("Fusion")
    QLocale.setDefault(QLocale(QLocale.Turkish, QLocale.Turkey)); window = TurkceAnaPencere(); window.show(); return app.exec()

if __name__ == "__main__": raise SystemExit(main())
