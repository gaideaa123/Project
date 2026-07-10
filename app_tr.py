from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import keyring
from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

import app as core

AYAR_SERVISI = "signaldesk-agency-console.app-settings"
VARSAYILAN_REDIRECT = "http://127.0.0.1:3455/callback/"
VARSAYILAN_KAPSAMLAR = "user.info.basic,video.publish"

METINLER = {
    "SIGNALDESK / AGENCY OPERATIONS": "SIGNALDESK / AJANS OPERASYONLARI",
    "SIGNALDESK / PUBLISH OPERATIONS": "SIGNALDESK / AJANS OPERASYONLARI",
    "Ship content with a paper trail.": "İçeriği kayıtlı, kontrollü ve güvenli yayınla.",
    "Content control, without the chaos.": "İçeriği kayıtlı, kontrollü ve güvenli yayınla.",
    "Profile Manager": "Profil Yönetimi", "Accounts": "Profil Yönetimi",
    "Batch Processing": "Toplu Medya İşleme", "Processing": "Toplu Medya İşleme",
    "Deployment Queue": "Yayın Kuyruğu", "Scheduler": "Yayın Kuyruğu",
    "Connect an official channel": "Resmî bir kanal bağla", "Connect a profile": "Resmî bir kanal bağla",
    "Profile": "Profil", "Profile name": "Profil", "Platform": "Platform",
    "Access token": "Erişim belirteci", "Refresh token": "Yenileme belirteci",
    "Network gateway": "Ağ geçidi", "Network proxy": "Ağ geçidi",
    "Add profile": "Profil ekle", "Authorized profiles": "Yetkilendirilmiş profiller",
    "Connected profiles": "Yetkilendirilmiş profiller", "Remove selected": "Seçileni kaldır",
    "Token": "Belirteç", "Token health": "Belirteç", "Network": "Ağ", "Added": "Eklenme",
    "H.264 rendition batch": "H.264 çıktı paketi", "Delivery renditions": "H.264 çıktı paketi",
    "Select master": "Ana dosyayı seç", "Choose video": "Ana dosyayı seç",
    "Select folder": "Çıktı klasörünü seç", "Start batch": "Toplu işlemi başlat",
    "Render outputs": "Toplu işlemi başlat", "Processing log": "İşlem günlüğü",
    "Live operations log": "İşlem günlüğü", "Browse": "Gözat",
    "Deployment time": "Yayın zamanı", "Run at": "Yayın zamanı", "Caption": "Açıklama",
    "Repeat daily": "Her gün tekrarla", "Queue deployment": "Yayını kuyruğa ekle",
    "Queue post": "Yayını kuyruğa ekle", "23-hour guarded pipeline": "23 saat korumalı yayın hattı",
    "Posting pipeline": "23 saat korumalı yayın hattı", "Run due jobs": "Zamanı gelenleri çalıştır",
    "Run due now": "Zamanı gelenleri çalıştır", "Asset": "Medya", "Video": "Medya",
    "Next run": "Sonraki çalışma", "Next deployment": "Sonraki çalışma",
    "Cadence": "Tekrar", "State": "Durum", "Publish ID": "Yayın kimliği",
}

DURUM = {
    "Ready": "Hazır", "Refresh soon": "Yakında yenilenecek", "Gateway": "Ağ geçidi",
    "Approved proxy": "Ağ geçidi", "Direct": "Doğrudan", "Daily": "Günlük",
    "Once": "Tek sefer", "Queued": "Kuyrukta", "Running": "Çalışıyor",
    "Failed": "Başarısız", "Submitted": "Gönderildi",
}


def kasa_oku(ad: str, varsayilan: str = "") -> str:
    try:
        return keyring.get_password(AYAR_SERVISI, ad) or varsayilan
    except Exception:
        return varsayilan


def ayarlari_yukle() -> None:
    values = {
        "TIKTOK_CLIENT_KEY": kasa_oku("client_key"),
        "TIKTOK_CLIENT_SECRET": kasa_oku("client_secret"),
        "TIKTOK_REDIRECT_URI": kasa_oku("redirect_uri", VARSAYILAN_REDIRECT),
        "TIKTOK_SCOPES": kasa_oku("scopes", VARSAYILAN_KAPSAMLAR),
    }
    for name, value in values.items():
        if value:
            os.environ[name] = value


class TurkceAnaPencere(core.MainWindow):
    def build_ui(self) -> None:
        super().build_ui()
        self.setWindowTitle("SignalDesk Ajans Paneli")
        self._cekirdek_uyumlulugunu_kur()
        self.tabs.addTab(self.api_sekmesi(), "API Ayarları")
        self._cevir()

    def _cekirdek_uyumlulugunu_kur(self) -> None:
        """Eski ve yeni app.py alanlarını tek kararlı arayüze uyarlar."""
        if not hasattr(self, "master") and hasattr(self, "master_video"):
            self.master = self.master_video
        if not hasattr(self, "batch_size") and hasattr(self, "variant_count"):
            self.batch_size = self.variant_count
        if not hasattr(self, "progress") and hasattr(self, "render_progress"):
            self.progress = self.render_progress

        if not hasattr(self, "output_dir"):
            self.output_dir = QLineEdit()
            self.output_dir.setPlaceholderText("Çıktı klasörünü seçin veya tam yolu yazın")
            self.output_dir.setClearButtonEnabled(True)
            button = QPushButton("Çıktı klasörünü seç")
            button.clicked.connect(self.choose_output)
            row = QHBoxLayout()
            row.addWidget(self.output_dir, 1)
            row.addWidget(button)
            processing_page = self.tabs.widget(1)
            page_layout = processing_page.layout() if processing_page else None
            controls = None
            if page_layout:
                for index in range(page_layout.count()):
                    item = page_layout.itemAt(index)
                    widget = item.widget()
                    if isinstance(widget, QFrame) and widget.layout():
                        controls = widget
                        break
            if controls and controls.layout():
                controls.layout().insertLayout(max(0, controls.layout().count() - 3), row)
            elif page_layout:
                page_layout.addLayout(row)

        self.output_dir.setReadOnly(False)
        self.output_dir.setClearButtonEnabled(True)
        self.output_dir.editingFinished.connect(self._normalize_output)

    def api_sekmesi(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 18, 0, 0)
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(16)
        title = QLabel("TikTok API ve OAuth Ayarları")
        title.setObjectName("sectionTitle")
        note = QLabel("Uygulama anahtarları güvenli kasada, profil belirteçleri Profil Yönetimi'nde saklanır.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(note)
        form = QFormLayout()
        self.client_key_alani = QLineEdit(kasa_oku("client_key"))
        self.client_secret_alani = QLineEdit(kasa_oku("client_secret"))
        self.client_secret_alani.setEchoMode(QLineEdit.Password)
        self.redirect_alani = QLineEdit(kasa_oku("redirect_uri", VARSAYILAN_REDIRECT))
        self.kapsam_alani = QLineEdit(kasa_oku("scopes", VARSAYILAN_KAPSAMLAR))
        form.addRow("Client Key", self.client_key_alani)
        form.addRow("Client Secret", self.client_secret_alani)
        form.addRow("Redirect URI", self.redirect_alani)
        form.addRow("OAuth kapsamları", self.kapsam_alani)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        save = QPushButton("Ayarları güvenli kasaya kaydet")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.api_kaydet)
        auth = QPushButton("Profil belirteçlerini al")
        auth.clicked.connect(self.oauth_ac)
        show = QCheckBox("Client Secret'ı göster")
        show.toggled.connect(lambda checked: self.client_secret_alani.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password))
        buttons.addWidget(save)
        buttons.addWidget(auth)
        buttons.addWidget(show)
        buttons.addStretch()
        layout.addLayout(buttons)
        steps = QLabel(
            "1. Developer Portal'da Login Kit ve Content Posting API ekle.\n"
            "2. Redirect URI'yi http://127.0.0.1:3455/callback/ yap.\n"
            "3. Sandbox Client Key ve Secret değerlerini kaydet.\n"
            "4. Profil belirteçlerini al, sonra Access/Refresh Token'ı Profil Yönetimi'ne gir."
        )
        steps.setObjectName("muted")
        steps.setWordWrap(True)
        layout.addWidget(steps)
        layout.addStretch()
        outer.addWidget(panel, 1)
        return page

    def api_kaydet(self, bilgi_goster: bool = True) -> bool:
        data = {
            "client_key": self.client_key_alani.text().strip(),
            "client_secret": self.client_secret_alani.text().strip(),
            "redirect_uri": self.redirect_alani.text().strip(),
            "scopes": self.kapsam_alani.text().strip(),
        }
        if not all(data.values()):
            QMessageBox.warning(self, "Eksik API ayarı", "Tüm API alanlarını doldurun.")
            return False
        try:
            for name, value in data.items():
                keyring.set_password(AYAR_SERVISI, name, value)
            ayarlari_yukle()
            if bilgi_goster:
                QMessageBox.information(self, "Kaydedildi", "API ayarları güvenli kasaya kaydedildi.")
            return True
        except Exception as exc:
            self.error("API ayarları kaydedilemedi", str(exc))
            return False

    def oauth_ac(self) -> None:
        if not self.api_kaydet(False):
            return
        helper = Path(__file__).with_name("oauth_helper.py")
        try:
            kwargs: dict[str, Any] = {"cwd": str(helper.parent), "env": os.environ.copy()}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
            subprocess.Popen([sys.executable, str(helper)], **kwargs)
        except Exception as exc:
            self.error("OAuth yardımcısı açılamadı", str(exc))

    def _cevir(self) -> None:
        for index, name in enumerate(("Profil Yönetimi", "Toplu Medya İşleme", "Yayın Kuyruğu", "API Ayarları")):
            if index < self.tabs.count():
                self.tabs.setTabText(index, name)
        for label in self.findChildren(QLabel):
            label.setText(METINLER.get(label.text(), label.text()))
        for button in self.findChildren(QPushButton):
            button.setText(METINLER.get(button.text(), button.text()))
        if hasattr(self, "accounts"):
            self.accounts.setHorizontalHeaderLabels(["Profil", "Platform", "Belirteç", "Ağ", "Eklenme"])
        elif hasattr(self, "accounts_table"):
            self.accounts_table.setHorizontalHeaderLabels(["Profil", "Belirteç", "Ağ", "Eklenme"])
        if hasattr(self, "jobs"):
            self.jobs.setHorizontalHeaderLabels(["Profil", "Medya", "Sonraki çalışma", "Tekrar", "Durum", "Yayın kimliği"])
        elif hasattr(self, "jobs_table"):
            self.jobs_table.setHorizontalHeaderLabels(["Profil", "Medya", "Sonraki çalışma", "Tekrar", "Durum", "Yayın kimliği"])
        if hasattr(self, "batch_size"):
            self.batch_size.setSuffix(" çıktı")
        if hasattr(self, "run_at"):
            self.run_at.setDisplayFormat("dd.MM.yyyy HH:mm")
        elif hasattr(self, "schedule_time"):
            self.schedule_time.setDisplayFormat("dd.MM.yyyy HH:mm")

    def refresh(self) -> None:
        if hasattr(super(), "refresh"):
            super().refresh()
        elif hasattr(super(), "refresh_all"):
            super().refresh_all()
        self._cevir()
        for table_name in ("accounts", "accounts_table"):
            table = getattr(self, table_name, None)
            if table:
                for row in range(table.rowCount()):
                    for column in range(table.columnCount()):
                        item = table.item(row, column)
                        if item:
                            item.setText(DURUM.get(item.text(), item.text()))

    def _normalize_output(self) -> None:
        if self.output_dir.text().strip():
            self.output_dir.setText(str(Path(self.output_dir.text().strip()).expanduser().resolve()))

    def choose_output(self) -> None:
        initial = self.output_dir.text().strip()
        if not initial or not Path(initial).exists():
            master_text = self.master.text().strip() if hasattr(self, "master") else ""
            initial = str(Path(master_text).parent) if master_text else str(Path.home())
        selected = QFileDialog.getExistingDirectory(
            self, "Çıktı klasörünü seç", initial,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not selected:
            return
        target = Path(selected).resolve()
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".signaldesk-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            self.error("Klasör kullanılamıyor", str(exc))
            return
        self.output_dir.setText(str(target))
        self.output_dir.repaint()
        QApplication.processEvents()
        if hasattr(self, "log"):
            self.log(f"Çıktı klasörü seçildi: {target}")

    def choose_master(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ana medya dosyasını seç", "", "Medya (*.mp4 *.mov *.mkv *.webm)")
        if path:
            self.master.setText(str(Path(path).resolve()))
            if not self.output_dir.text().strip():
                source = Path(path).resolve()
                self.output_dir.setText(str(source.parent / f"{source.stem}-ciktilar"))

    def start_batch(self) -> None:
        source = Path(self.master.text().strip())
        target = Path(self.output_dir.text().strip()) if self.output_dir.text().strip() else Path()
        if not source.is_file() or not self.output_dir.text().strip():
            self.error("Eksik dosya yolu", "Ana medya dosyasını ve çıktı klasörünü seçin.")
            return
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.error("Çıktı klasörü oluşturulamadı", str(exc))
            return
        count = self.batch_size.value()

        if hasattr(self, "encoder") and hasattr(self, "runner"):
            self.render_button.setEnabled(False)
            self.progress.setValue(0)
            signals = self.runner.start(lambda channel: self.encoder.encode(source, target, count, channel))
            signals.log.connect(self.log)
            signals.progress.connect(self.progress.setValue)
            signals.result.connect(self._batch_done)
            signals.error.connect(lambda detail: self.error("Toplu işlem başarısız", detail))
            signals.finished.connect(lambda: self.render_button.setEnabled(True))
            return

        if hasattr(core, "Worker") and hasattr(self, "renderer") and hasattr(self, "pool"):
            self.render_button.setEnabled(False)
            self.progress.setValue(0)
            worker = core.Worker(lambda signals: self.renderer.render_many(source, count, target, signals))
            worker.signals.log.connect(self.log)
            worker.signals.progress.connect(self.progress.setValue)
            worker.signals.result.connect(self._batch_done)
            worker.signals.error.connect(lambda detail: self.error("Toplu işlem başarısız", detail))
            worker.signals.finished.connect(lambda: self.render_button.setEnabled(True))
            self.pool.start(worker)
            return
        self.error("Çekirdek uyumsuz", "Video işleme motoru bulunamadı.")

    def _batch_done(self, outputs: object) -> None:
        self.last_outputs = list(outputs or [])
        queue_field = getattr(self, "queue_video", getattr(self, "schedule_video", None))
        if queue_field and self.last_outputs:
            queue_field.setText(self.last_outputs[0])
        self.log(f"{len(self.last_outputs)} çıktı tamamlandı")

    def start_render(self) -> None:
        self.start_batch()

    def error(self, title: str, details: str) -> None:
        if hasattr(super(), "error"):
            super().error(title, details)
        else:
            super().show_error(title, details)


def main() -> int:
    ayarlari_yukle()
    app = QApplication(sys.argv)
    app.setApplicationName("SignalDesk Ajans Paneli")
    app.setOrganizationName("SignalDesk")
    app.setStyle("Fusion")
    QLocale.setDefault(QLocale(QLocale.Turkish, QLocale.Turkey))
    window = TurkceAnaPencere()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
