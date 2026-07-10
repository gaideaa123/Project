from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import ffmpeg
import keyring
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
    QWidget,
)

import app as core

AYAR_SERVISI = "signaldesk-agency-console.app-settings"
REDIRECT = "http://127.0.0.1:3455/callback/"
KAPSAMLAR = "user.info.basic,video.publish"
MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}

CEVIRI = {
    "Profiles": "Profil Yönetimi", "Accounts": "Profil Yönetimi",
    "Asset processing": "Tek Tık Video", "Processing": "Tek Tık Video",
    "Deployment queue": "Yayın Kuyruğu", "Scheduler": "Yayın Kuyruğu",
    "Choose video": "Input video seç", "Select master": "Input video seç",
    "Render outputs": "Tek tıkla varyant oluştur", "Start batch": "Tek tıkla varyant oluştur",
    "Live operations log": "Üretim günlüğü", "Processing log": "Üretim günlüğü",
    "Browse": "Gözat", "Caption": "Açıklama", "Run at": "Yayın zamanı",
    "Queue post": "Yayını kuyruğa ekle", "Run due now": "Zamanı gelenleri çalıştır",
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


def _ffmpeg_ready() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class OneClickVariantEngine:
    """Creates real editorial variants from one source without extra asset setup."""

    def __init__(self, registry: Any, logger: Any):
        self.registry = registry
        self.logger = logger

    @staticmethod
    def _probe(path: Path) -> tuple[float, bool]:
        data = ffmpeg.probe(str(path))
        duration = float(data.get("format", {}).get("duration") or 0)
        has_audio = any(stream.get("codec_type") == "audio" for stream in data.get("streams", []))
        if duration <= 0:
            raise RuntimeError(f"Video süresi okunamadı: {path.name}")
        return duration, has_audio

    def render(self, source: Path, output: Path, count: int, signals: Any) -> list[str]:
        if not _ffmpeg_ready():
            raise RuntimeError("FFmpeg ve FFprobe PATH üzerinde bulunamadı")
        if not source.is_file() or source.suffix.lower() not in MEDIA_EXTENSIONS:
            raise RuntimeError("Geçerli bir input video seçin")
        output.mkdir(parents=True, exist_ok=True)
        duration, has_audio = self._probe(source)
        rng = random.SystemRandom()
        results: list[str] = []

        for index in range(count):
            speed = rng.uniform(0.985, 1.018)
            zoom = rng.uniform(1.006, 1.035)
            saturation = rng.uniform(0.97, 1.06)
            contrast = rng.uniform(0.985, 1.04)
            brightness = rng.uniform(-0.012, 0.012)
            trim = min(rng.uniform(0.0, 0.16), max(0.0, duration - 1.0))
            flip = rng.choice((False, False, False, True))
            target = output / f"{source.stem}-variant-{index + 1:03d}-{uuid.uuid4().hex[:7]}.mp4"

            filters = [
                f"setpts=PTS/{speed:.6f}",
                "scale=1080:1920:force_original_aspect_ratio=increase",
                f"scale=iw*{zoom:.6f}:ih*{zoom:.6f}",
                "crop=1080:1920",
                f"eq=saturation={saturation:.6f}:contrast={contrast:.6f}:brightness={brightness:.6f}",
                "unsharp=5:5:0.22:3:3:0.0",
            ]
            if flip:
                filters.append("hflip")
            filters.append("format=yuv420p")

            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{trim:.3f}", "-i", str(source),
                "-map", "0:v:0", "-map", "0:a:0?", "-vf", ",".join(filters),
            ]
            if has_audio:
                command += ["-af", f"atempo={speed:.6f},loudnorm=I=-14:TP=-1.5:LRA=11"]
            command += [
                "-c:v", "libx264", "-preset", "medium", "-crf", "21",
                "-profile:v", "high", "-level", "4.1", "-c:a", "aac",
                "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
                "-map_metadata", "-1", str(target),
            ]
            signals.log.emit(f"{index + 1}/{count}: {target.name}")
            completed = subprocess.run(command, capture_output=True, text=True)
            if completed.returncode:
                raise RuntimeError(completed.stderr.strip() or "FFmpeg üretimi başarısız")

            results.append(str(target.resolve()))
            signals.progress.emit(round((index + 1) * 100 / count))
        return results


class TurkceAnaPencere(core.MainWindow):
    def build_ui(self) -> None:
        super().build_ui()
        self.setWindowTitle("SignalDesk Tek Tık Video")
        self._discover_processing_widgets()
        self._add_output_control()
        self.variant_engine = OneClickVariantEngine(self.registry, self.logger)
        self.tabs.addTab(self._api_tab(), "API Ayarları")
        self._translate()

    def _processing_page(self) -> QWidget:
        if not hasattr(self, "tabs") or self.tabs.count() < 2:
            raise RuntimeError("Medya sekmesi bulunamadı")
        return self.tabs.widget(1)

    def _discover_processing_widgets(self) -> None:
        page = self._processing_page()
        edits = page.findChildren(QLineEdit)
        spins = page.findChildren(QSpinBox)
        bars = page.findChildren(QProgressBar)

        def valid(value: object, kind: type) -> Any:
            return value if isinstance(value, kind) else None

        self.master = (
            valid(getattr(self, "master", None), QLineEdit)
            or valid(getattr(self, "master_video", None), QLineEdit)
            or valid(getattr(self, "source_video", None), QLineEdit)
            or (edits[0] if edits else None)
        )
        self.batch_size = (
            valid(getattr(self, "batch_size", None), QSpinBox)
            or valid(getattr(self, "variant_count", None), QSpinBox)
            or (spins[0] if spins else None)
        )
        self.progress = (
            valid(getattr(self, "progress", None), QProgressBar)
            or valid(getattr(self, "render_progress", None), QProgressBar)
            or (bars[0] if bars else None)
        )

        layout = page.layout()
        if self.master is None:
            self.master = QLineEdit()
            self.master.setPlaceholderText("Input video")
            if layout:
                layout.addWidget(self.master)
        if self.batch_size is None:
            self.batch_size = QSpinBox()
            if layout:
                layout.addWidget(self.batch_size)
        if self.progress is None:
            self.progress = QProgressBar()
            if layout:
                layout.addWidget(self.progress)

        self.batch_size.setRange(1, 100)
        if self.batch_size.value() < 1:
            self.batch_size.setValue(5)
        self.batch_size.setSuffix(" varyant")

    def _processing_layout(self):
        page = self._processing_page()
        frames = [frame for frame in page.findChildren(QFrame) if frame.layout()]
        return frames[0].layout() if frames else page.layout()

    def _add_output_control(self) -> None:
        self.output_dir = QLineEdit()
        self.output_dir.setPlaceholderText("Output klasörü")
        self.output_dir.setClearButtonEnabled(True)
        button = QPushButton("Output seç")
        button.clicked.connect(self.choose_output)
        row = QHBoxLayout()
        row.addWidget(self.output_dir, 1)
        row.addWidget(button)
        layout = self._processing_layout()
        if layout:
            layout.insertLayout(max(1, layout.count() - 2), row)

    def choose_output(self) -> None:
        initial = self.output_dir.text().strip() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Output klasörünü seç", initial)
        if selected:
            self.output_dir.setText(str(Path(selected).resolve()))

    def choose_master(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Input video seç", "", "Video (*.mp4 *.mov *.mkv *.webm *.m4v)"
        )
        if path:
            source = Path(path).resolve()
            self.master.setText(str(source))
            if not self.output_dir.text().strip():
                self.output_dir.setText(str(source.parent / f"{source.stem}-variants"))

    def start_batch(self) -> None:
        source = Path(self.master.text().strip())
        if not source.is_file():
            self.error("Input bulunamadı", "Geçerli bir video seçin")
            return
        output_text = self.output_dir.text().strip()
        output = Path(output_text) if output_text else source.parent / f"{source.stem}-variants"
        self.output_dir.setText(str(output.resolve()))
        count = self.batch_size.value()
        button = getattr(self, "render_button", None)
        if button:
            button.setEnabled(False)
        self.progress.setValue(0)
        task = core.BackgroundTask(lambda signals: self.variant_engine.render(source, output, count, signals))
        task.signals.log.connect(self.log)
        task.signals.progress.connect(self.progress.setValue)
        task.signals.result.connect(self._variant_done)
        task.signals.error.connect(lambda detail: self.error("Üretim başarısız", detail))
        task.signals.finished.connect(lambda current=task: self._variant_finished(current))
        self.tasks.add(task)
        task.start()

    def start_render(self) -> None:
        self.start_batch()

    def _variant_done(self, outputs: object) -> None:
        self.last_outputs = list(outputs or [])
        queue_field = getattr(self, "queue_video", getattr(self, "schedule_video", None))
        if queue_field is not None and self.last_outputs:
            queue_field.setText(self.last_outputs[0])
        self.log(f"{len(self.last_outputs)} varyant hazır: {self.output_dir.text()}")

    def _variant_finished(self, task: object) -> None:
        self.tasks.discard(task)
        button = getattr(self, "render_button", None)
        if button:
            button.setEnabled(True)

    def _api_tab(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)
        panel = QFrame()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("TikTok API ve OAuth Ayarları"))
        form = QFormLayout()
        self.client_key_field = QLineEdit(kasa_oku("client_key"))
        self.client_secret_field = QLineEdit(kasa_oku("client_secret"))
        self.client_secret_field.setEchoMode(QLineEdit.Password)
        self.redirect_field = QLineEdit(kasa_oku("redirect_uri", REDIRECT))
        self.scopes_field = QLineEdit(kasa_oku("scopes", KAPSAMLAR))
        form.addRow("Client Key", self.client_key_field)
        form.addRow("Client Secret", self.client_secret_field)
        form.addRow("Redirect URI", self.redirect_field)
        form.addRow("OAuth kapsamları", self.scopes_field)
        layout.addLayout(form)
        save = QPushButton("Ayarları güvenli kasaya kaydet")
        save.clicked.connect(self.save_api)
        layout.addWidget(save)
        outer.addWidget(panel)
        return page

    def save_api(self) -> None:
        data = {
            "client_key": self.client_key_field.text().strip(),
            "client_secret": self.client_secret_field.text().strip(),
            "redirect_uri": self.redirect_field.text().strip(),
            "scopes": self.scopes_field.text().strip(),
        }
        if not all(data.values()):
            QMessageBox.warning(self, "Eksik API ayarı", "Tüm API alanlarını doldurun")
            return
        for name, value in data.items():
            keyring.set_password(AYAR_SERVISI, name, value)
        ayarlari_yukle()
        QMessageBox.information(self, "Kaydedildi", "API ayarları güvenli kasaya kaydedildi")

    def _translate(self) -> None:
        names = ("Profil Yönetimi", "Tek Tık Video", "Yayın Kuyruğu", "API Ayarları")
        for index, name in enumerate(names):
            if index < self.tabs.count():
                self.tabs.setTabText(index, name)
        for label in self.findChildren(QLabel):
            label.setText(CEVIRI.get(label.text(), label.text()))
        for button in self.findChildren(QPushButton):
            button.setText(CEVIRI.get(button.text(), button.text()))

    def refresh(self) -> None:
        parent = getattr(super(), "refresh", None)
        if callable(parent):
            parent()
        else:
            fallback = getattr(super(), "refresh_all", None)
            if callable(fallback):
                fallback()
        self._translate()

    def error(self, title: str, details: str) -> None:
        parent = getattr(super(), "error", None)
        if callable(parent):
            parent(title, details)
        else:
            QMessageBox.critical(self, title, details)


def main() -> int:
    ayarlari_yukle()
    app = QApplication(sys.argv)
    app.setApplicationName("SignalDesk Tek Tık Video")
    app.setOrganizationName("SignalDesk")
    app.setStyle("Fusion")
    QLocale.setDefault(QLocale(QLocale.Turkish, QLocale.Turkey))
    window = TurkceAnaPencere()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
