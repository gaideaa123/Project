from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from web_upload_engine import WebUploadRequest, run_upload


class BrowserPublishWorker(QThread):
    status = Signal(str)
    ready = Signal()
    completed = Signal()
    failed = Signal(str)

    def __init__(self, request: WebUploadRequest, parent=None):
        super().__init__(parent)
        self.request = request
        self.confirm_event = threading.Event()
        self.cancel_event = threading.Event()

    def confirm_publish(self) -> None:
        self.confirm_event.set()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            run_upload(
                self.request,
                self.confirm_event,
                self.cancel_event,
                self.status.emit,
                self.ready.emit,
            )
            self.completed.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class WebPublishPanel(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        self.worker: BrowserPublishWorker | None = None
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 28)
        outer.setSpacing(16)

        title = QLabel("TikTok Studio web yayını")
        title.setStyleSheet("font-size: 22px; font-weight: 700")
        outer.addWidget(title)
        note = QLabel(
            "Chrome görünür açılır. Giriş, CAPTCHA ve 2FA adımlarını tarayıcıda siz tamamlarsınız. "
            "Video ve caption otomatik hazırlanır; yayın yalnız bu ekrandaki açık onayınızdan sonra tıklanır."
        )
        note.setWordWrap(True)
        outer.addWidget(note)

        form = QFormLayout()
        self.profile = QLineEdit("hesap1")
        self.profile.setPlaceholderText("Örn: hesap1, emre, marka-tr")
        form.addRow("Tarayıcı profili", self.profile)

        self.video = QLineEdit()
        self.video.setPlaceholderText(r"C:\Users\ahmet\Music\cikti\1.mp4")
        choose_video = QPushButton("Video seç")
        choose_video.clicked.connect(self.choose_video)
        video_row = QHBoxLayout()
        video_row.addWidget(self.video, 1)
        video_row.addWidget(choose_video)
        form.addRow("Video", video_row)
        outer.addLayout(form)

        outer.addWidget(QLabel("Caption"))
        self.caption = QPlainTextEdit()
        self.caption.setPlaceholderText("Azure GPT-4o ile üretilen veya elle yazılan caption")
        self.caption.setMinimumHeight(150)
        outer.addWidget(self.caption)

        caption_row = QHBoxLayout()
        from_file = QPushButton("Caption dosyası aç")
        from_file.clicked.connect(self.choose_caption)
        use_latest = QPushButton("Son numaralı videoyu seç")
        use_latest.clicked.connect(self.select_latest_video)
        caption_row.addWidget(from_file)
        caption_row.addWidget(use_latest)
        caption_row.addStretch()
        outer.addLayout(caption_row)

        self.review_check = QCheckBox("Video, caption, hedef hesap ve görünürlük ayarlarını tarayıcıda kontrol edeceğim")
        self.review_check.toggled.connect(self._sync_buttons)
        outer.addWidget(self.review_check)

        actions = QHBoxLayout()
        self.prepare_button = QPushButton("TARAYICIYI AÇ VE YAYINI HAZIRLA")
        self.prepare_button.setMinimumHeight(48)
        self.prepare_button.clicked.connect(self.prepare)
        self.publish_button = QPushButton("ONAYLA VE YAYINLA")
        self.publish_button.setMinimumHeight(48)
        self.publish_button.setEnabled(False)
        self.publish_button.clicked.connect(self.confirm)
        self.cancel_button = QPushButton("İptal")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        actions.addWidget(self.prepare_button, 1)
        actions.addWidget(self.publish_button, 1)
        actions.addWidget(self.cancel_button)
        outer.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        outer.addWidget(self.progress)
        self.status = QLabel("Hazır")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        outer.addStretch()

    def choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "TikTok videosu seç", "", "Video (*.mp4 *.mov *.m4v *.webm)")
        if path:
            self.video.setText(str(Path(path).resolve()))

    def choose_caption(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Caption dosyası seç", "", "Metin (*.txt);;Tüm dosyalar (*)")
        if not path:
            return
        try:
            self.caption.setPlainText(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.critical(self, "Caption okunamadı", str(exc))

    def select_latest_video(self) -> None:
        folder = Path(r"C:\Users\ahmet\Music\cikti")
        numbered = []
        for path in folder.glob("*.mp4"):
            try:
                numbered.append((int(path.stem), path))
            except ValueError:
                continue
        if not numbered:
            QMessageBox.warning(self, "Video yok", f"Numaralı MP4 bulunamadı:\n{folder}")
            return
        self.video.setText(str(max(numbered)[1].resolve()))

    def prepare(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        request = WebUploadRequest(
            self.profile.text().strip(),
            Path(self.video.text().strip()).expanduser().resolve(),
            self.caption.toPlainText().strip(),
        )
        try:
            request.validate()
        except Exception as exc:
            QMessageBox.warning(self, "Eksik veya geçersiz alan", str(exc))
            return
        self.review_check.setChecked(False)
        self.prepare_button.setEnabled(False)
        self.publish_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setVisible(True)
        self.status.setText("Chrome başlatılıyor")
        self.worker = BrowserPublishWorker(request, self)
        self.worker.status.connect(self.status.setText)
        self.worker.ready.connect(self.on_ready)
        self.worker.completed.connect(self.on_completed)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_ready(self) -> None:
        self.status.setText("Yayın hazır. Tarayıcı önizlemesini kontrol edip kutuyu işaretleyin")
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        running = self.worker is not None and self.worker.isRunning()
        waiting = running and self.status.text().startswith("Yayın hazır")
        self.publish_button.setEnabled(waiting and self.review_check.isChecked())

    def confirm(self) -> None:
        if self.worker is None or not self.worker.isRunning() or not self.review_check.isChecked():
            return
        self.publish_button.setEnabled(False)
        self.review_check.setEnabled(False)
        self.status.setText("Yayın onaylandı, TikTok'ta Yayınla tıklanıyor")
        self.worker.confirm_publish()

    def cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
        self.cancel_button.setEnabled(False)
        self.status.setText("İptal ediliyor")

    def on_completed(self) -> None:
        self.progress.setVisible(False)
        self.status.setText("Yayın TikTok tarafından kabul edildi")
        QMessageBox.information(self, "Tamamlandı", "TikTok web yayını kabul edildi.")

    def on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.status.setText("Yayın başarısız")
        QMessageBox.critical(self, "Web yayın hatası", message)

    def on_finished(self) -> None:
        self.prepare_button.setEnabled(True)
        self.publish_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.review_check.setEnabled(True)
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()


def install_web_publish_tab(window) -> None:
    if getattr(window, "_web_publish_installed", False):
        return
    tabs = getattr(window, "tabs", None)
    if tabs is None:
        return
    window._web_publish_installed = True
    window.web_publish_panel = WebPublishPanel(window)
    index = max(0, tabs.count() - 1)
    tabs.insertTab(index, window.web_publish_panel, "Web Yayını")
