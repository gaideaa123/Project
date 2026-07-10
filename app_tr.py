from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import keyring
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

import app as core

AYAR_SERVISI = "signaldesk-agency-console.app-settings"
REDIRECT = "http://127.0.0.1:3455/callback/"
KAPSAMLAR = "user.info.basic,video.publish"

CEVIRI = {
    "Profiles": "Profil Yönetimi", "Accounts": "Profil Yönetimi",
    "Asset processing": "Toplu Medya İşleme", "Processing": "Toplu Medya İşleme",
    "Deployment queue": "Yayın Kuyruğu", "Scheduler": "Yayın Kuyruğu",
    "Connect an official channel": "Resmî bir kanal bağla",
    "Connected profiles": "Yetkilendirilmiş profiller",
    "Add profile": "Profil ekle", "Remove selected": "Seçileni kaldır",
    "Profile": "Profil", "Platform": "Platform", "Token": "Belirteç",
    "Last post": "Son yayın", "Added": "Eklenme",
    "Access token": "Erişim belirteci", "Refresh token": "Yenileme belirteci",
    "H.264 delivery batch": "H.264 çıktı paketi",
    "Choose video": "Ana dosyayı seç", "Select master": "Ana dosyayı seç",
    "Render outputs": "Toplu işlemi başlat", "Start batch": "Toplu işlemi başlat",
    "Live operations log": "İşlem günlüğü", "Processing log": "İşlem günlüğü",
    "Browse": "Gözat", "Caption": "Açıklama", "Run at": "Yayın zamanı",
    "Repeat daily": "Her gün tekrarla", "Queue post": "Yayını kuyruğa ekle",
    "Posting pipeline": "23 saat korumalı yayın hattı",
    "Run due now": "Zamanı gelenleri çalıştır", "Video": "Medya",
    "Next deployment": "Sonraki çalışma", "Cadence": "Tekrar",
    "State": "Durum", "Publish ID": "Yayın kimliği",
    "READY": "HAZIR",
}

DURUM = {
    "Ready": "Hazır", "Refresh soon": "Yakında yenilenecek",
    "Direct": "Doğrudan", "Daily": "Günlük", "Once": "Tek sefer",
    "Queued": "Kuyrukta", "Running": "Çalışıyor", "Failed": "Başarısız",
    "Submitted": "Gönderildi",
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
        "TIKTOK_REDIRECT_URI": kasa_oku("redirect_uri", REDIRECT),
        "TIKTOK_SCOPES": kasa_oku("scopes", KAPSAMLAR),
    }
    for name, value in values.items():
        if value:
            os.environ[name] = value


class TurkceAnaPencere(core.MainWindow):
    def build_ui(self) -> None:
        super().build_ui()
        self.setWindowTitle("SignalDesk Ajans Paneli")
        self._isleme_widgetlarini_bul()
        self.tabs.addTab(self._api_sekmesi(), "API Ayarları")
        self._cevir()

    def _isleme_widgetlarini_bul(self) -> None:
        """Çekirdek alan adları değişse bile gerçek Qt widget'larını keşfeder."""
        page = self.tabs.widget(1)
        if page is None:
            raise RuntimeError("Toplu medya işleme sekmesi bulunamadı")

        if not hasattr(self, "master"):
            for name in ("master_video", "master_path", "source_video", "source_path"):
                candidate = getattr(self, name, None)
                if isinstance(candidate, QLineEdit):
                    self.master = candidate
                    break
        if not hasattr(self, "master"):
            edits = page.findChildren(QLineEdit)
            if edits:
                self.master = edits[0]
        if not hasattr(self, "master"):
            raise RuntimeError("Ana medya alanı bulunamadı")

        if not hasattr(self, "batch_size"):
            for name in ("variant_count", "rendition_count", "count", "output_count"):
                candidate = getattr(self, name, None)
                if isinstance(candidate, QSpinBox):
                    self.batch_size = candidate
                    break
        if not hasattr(self, "batch_size"):
            spins = page.findChildren(QSpinBox)
            if spins:
                self.batch_size = spins[0]
        if not hasattr(self, "batch_size"):
            self.batch_size = QSpinBox(page)
            self.batch_size.setRange(1, 100)
            self.batch_size.setValue(3)
            page.layout().addWidget(self.batch_size)

        if not hasattr(self, "progress"):
            for name in ("render_progress", "batch_progress"):
                candidate = getattr(self, name, None)
                if isinstance(candidate, QProgressBar):
                    self.progress = candidate
                    break
        if not hasattr(self, "progress"):
            bars = page.findChildren(QProgressBar)
            if bars:
                self.progress = bars[0]
        if not hasattr(self, "progress"):
            self.progress = QProgressBar(page)
            page.layout().addWidget(self.progress)

        if not hasattr(self, "render_button"):
            buttons = page.findChildren(QPushButton)
            preferred = next(
                (button for button in buttons if any(word in button.text().lower() for word in ("render", "batch", "işlem"))),
                None,
            )
            if preferred:
                self.render_button = preferred

        if not hasattr(self, "output_dir"):
            self.output_dir = QLineEdit(page)
            self.output_dir.setPlaceholderText("Çıktı klasörünü seçin veya tam yolu yazın")
            self.output_dir.setClearButtonEnabled(True)
            button = QPushButton("Çıktı klasörünü seç", page)
            button.clicked.connect(self.choose_output)
            row = QHBoxLayout()
            row.addWidget(self.output_dir, 1)
            row.addWidget(button)
            container = next((frame for frame in page.findChildren(QFrame) if frame.layout()), None)
            if container:
                container.layout().insertLayout(max(0, container.layout().count() - 3), row)
            else:
                page.layout().addLayout(row)
        self.output_dir.setReadOnly(False)
        self.output_dir.setClearButtonEnabled(True)
        self.output_dir.editingFinished.connect(self._normalize_output)
        self.batch_size.setRange(1, 100)
        self.batch_size.setSuffix(" çıktı")

    def _api_sekmesi(self) -> QWidget:
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
        note = QLabel("Client Key ve Client Secret güvenli kasada tutulur. Profil belirteçleri Profil Yönetimi'nden eklenir.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(note)
        form = QFormLayout()
        self.client_key_alani = QLineEdit(kasa_oku("client_key"))
        self.client_secret_alani = QLineEdit(kasa_oku("client_secret"))
        self.client_secret_alani.setEchoMode(QLineEdit.Password)
        self.redirect_alani = QLineEdit(kasa_oku("redirect_uri", REDIRECT))
        self.kapsam_alani = QLineEdit(kasa_oku("scopes", KAPSAMLAR))
        form.addRow("Client Key", self.client_key_alani)
        form.addRow("Client Secret", self.client_secret_alani)
        form.addRow("Redirect URI", self.redirect_alani)
        form.addRow("OAuth kapsamları", self.kapsam_alani)
        layout.addLayout(form)
        row = QHBoxLayout()
        save = QPushButton("Ayarları güvenli kasaya kaydet")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.api_kaydet)
        auth = QPushButton("Profil belirteçlerini al")
        auth.clicked.connect(self.oauth_ac)
        show = QCheckBox("Client Secret'ı göster")
        show.toggled.connect(lambda value: self.client_secret_alani.setEchoMode(QLineEdit.Normal if value else QLineEdit.Password))
        row.addWidget(save)
        row.addWidget(auth)
        row.addWidget(show)
        row.addStretch()
        layout.addLayout(row)
        steps = QLabel(
            "1. Sandbox'ta Login Kit ve Content Posting API ekle.\n"
            "2. Redirect URI'yi http://127.0.0.1:3455/callback/ yap.\n"
            "3. Sandbox Client Key ve Secret değerlerini kaydet.\n"
            "4. Profil belirteçlerini al ve Profil Yönetimi'ne ekle."
        )
        steps.setObjectName("muted")
        steps.setWordWrap(True)
        layout.addWidget(steps)
        layout.addStretch()
        outer.addWidget(panel, 1)
        return page

    def api_kaydet(self, bilgi: bool = True) -> bool:
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
            if bilgi:
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
        tab_names = ("Profil Yönetimi", "Toplu Medya İşleme", "Yayın Kuyruğu", "API Ayarları")
        for index, name in enumerate(tab_names):
            if index < self.tabs.count():
                self.tabs.setTabText(index, name)
        for label in self.findChildren(QLabel):
            label.setText(CEVIRI.get(label.text(), label.text()))
        for button in self.findChildren(QPushButton):
            button.setText(CEVIRI.get(button.text(), button.text()))
        accounts = getattr(self, "accounts", getattr(self, "accounts_table", None))
        if accounts:
            headers = ["Profil", "Platform", "Belirteç", "Son yayın", "Eklenme"]
            accounts.setHorizontalHeaderLabels(headers[:accounts.columnCount()])
        jobs = getattr(self, "jobs", getattr(self, "jobs_table", None))
        if jobs:
            jobs.setHorizontalHeaderLabels(["Profil", "Medya", "Sonraki çalışma", "Tekrar", "Durum", "Yayın kimliği"][:jobs.columnCount()])

    def refresh(self) -> None:
        parent_refresh = getattr(super(), "refresh", None)
        if callable(parent_refresh):
            parent_refresh()
        else:
            parent_refresh_all = getattr(super(), "refresh_all", None)
            if callable(parent_refresh_all):
                parent_refresh_all()
        self._cevir()
        for name in ("accounts", "accounts_table", "jobs", "jobs_table"):
            table = getattr(self, name, None)
            if not table:
                continue
            for row in range(table.rowCount()):
                for column in range(table.columnCount()):
                    item = table.item(row, column)
                    if item:
                        item.setText(DURUM.get(item.text(), item.text()))

    def _normalize_output(self) -> None:
        text = self.output_dir.text().strip()
        if text:
            self.output_dir.setText(str(Path(text).expanduser().resolve()))

    def choose_output(self) -> None:
        initial = self.output_dir.text().strip()
        if not initial or not Path(initial).exists():
            initial = str(Path(self.master.text()).parent) if self.master.text().strip() else str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Çıktı klasörünü seç", initial, QFileDialog.ShowDirsOnly)
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
        self.log(f"Çıktı klasörü seçildi: {target}")

    def choose_master(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ana medya dosyasını seç", "", "Medya (*.mp4 *.mov *.mkv *.webm)")
        if path:
            source = Path(path).resolve()
            self.master.setText(str(source))
            if not self.output_dir.text().strip():
                self.output_dir.setText(str(source.parent / f"{source.stem}-ciktilar"))

    def start_batch(self) -> None:
        source = Path(self.master.text().strip())
        output_text = self.output_dir.text().strip()
        if not source.is_file() or not output_text:
            self.error("Eksik dosya yolu", "Ana medya dosyasını ve çıktı klasörünü seçin.")
            return
        output = Path(output_text)
        try:
            output.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.error("Çıktı klasörü oluşturulamadı", str(exc))
            return
        count = int(self.batch_size.value())
        button = getattr(self, "render_button", None)
        if button:
            button.setEnabled(False)
        self.progress.setValue(0)

        if hasattr(self, "engine") and hasattr(core, "BackgroundTask"):
            task = core.BackgroundTask(lambda signals: self.engine.render(source, output, count, signals))
            task.signals.log.connect(self.log)
            task.signals.progress.connect(self.progress.setValue)
            task.signals.result.connect(self._batch_done)
            task.signals.error.connect(lambda detail: self.error("Toplu işlem başarısız", detail))
            task.signals.finished.connect(lambda current=task: self._task_finished(current))
            if hasattr(self, "tasks"):
                self.tasks.add(task)
            task.start()
            return

        if hasattr(self, "encoder") and hasattr(self, "runner"):
            signals = self.runner.start(lambda channel: self.encoder.encode(source, output, count, channel))
            signals.log.connect(self.log)
            signals.progress.connect(self.progress.setValue)
            signals.result.connect(self._batch_done)
            signals.error.connect(lambda detail: self.error("Toplu işlem başarısız", detail))
            signals.finished.connect(lambda: self._enable_render_button())
            return

        if hasattr(self, "renderer") and hasattr(core, "Worker") and hasattr(self, "pool"):
            worker = core.Worker(lambda signals: self.renderer.render_many(source, count, output, signals))
            worker.signals.log.connect(self.log)
            worker.signals.progress.connect(self.progress.setValue)
            worker.signals.result.connect(self._batch_done)
            worker.signals.error.connect(lambda detail: self.error("Toplu işlem başarısız", detail))
            worker.signals.finished.connect(self._enable_render_button)
            self.pool.start(worker)
            return
        self._enable_render_button()
        self.error("Çekirdek uyumsuz", "Video işleme motoru bulunamadı.")

    def _task_finished(self, task: object) -> None:
        if hasattr(self, "tasks"):
            self.tasks.discard(task)
        self._enable_render_button()

    def _enable_render_button(self) -> None:
        button = getattr(self, "render_button", None)
        if button:
            button.setEnabled(True)

    def _batch_done(self, outputs: object) -> None:
        self.last_outputs = list(outputs or [])
        queue_field = getattr(self, "queue_video", getattr(self, "schedule_video", None))
        if queue_field and self.last_outputs:
            queue_field.setText(self.last_outputs[0])
        self.log(f"{len(self.last_outputs)} çıktı tamamlandı")

    def start_render(self) -> None:
        self.start_batch()

    def error(self, title: str, details: str) -> None:
        parent_error = getattr(super(), "error", None)
        if callable(parent_error):
            parent_error(title, details)
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
