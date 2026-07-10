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


class OneClickVariantEngine:
    def __init__(self, registry: Any, logger: Any):
        self.registry = registry
        self.logger = logger

    @staticmethod
    def probe(path: Path) -> tuple[float, bool]:
        data = ffmpeg.probe(str(path))
        duration = float(data.get("format", {}).get("duration") or 0)
        audio = any(stream.get("codec_type") == "audio" for stream in data.get("streams", []))
        if duration <= 0:
            raise RuntimeError(f"Video süresi okunamadı: {path.name}")
        return duration, audio

    def render(self, source: Path, output: Path, count: int, signals: Any) -> list[str]:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise RuntimeError("FFmpeg ve FFprobe PATH üzerinde bulunamadı")
        if not source.is_file() or source.suffix.lower() not in MEDIA_EXTENSIONS:
            raise RuntimeError("Geçerli bir input video seçin")

        output.mkdir(parents=True, exist_ok=True)
        duration, has_audio = self.probe(source)
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
        self.variant_engine = OneClickVariantEngine(self.registry, self.logger)
        self.tabs.insertTab(1, self._one_click_tab(), "Tek Tık Video")
        self.tabs.addTab(self._api_tab(), "API Ayarları")

    def _one_click_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 24, 24, 24)
        title = QLabel("Input ve output seç, gerisini tek tıkla hallet")
        title.setStyleSheet("font-size: 20px; font-weight: 700")
        outer.addWidget(title)

        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        form = QFormLayout()

        self.master = QLineEdit()
        self.master.setPlaceholderText("Input video")
        input_button = QPushButton("Input seç")
        input_button.clicked.connect(self.choose_master)
        input_row = QHBoxLayout()
        input_row.addWidget(self.master, 1)
        input_row.addWidget(input_button)
        form.addRow("Input", input_row)

        self.output_dir = QLineEdit()
        self.output_dir.setPlaceholderText("Output klasörü")
        output_button = QPushButton("Output seç")
        output_button.clicked.connect(self.choose_output)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_dir, 1)
        output_row.addWidget(output_button)
        form.addRow("Output", output_row)

        self.batch_size = QSpinBox()
        self.batch_size.setRange(1, 100)
        self.batch_size.setValue(5)
        self.batch_size.setSuffix(" varyant")
        form.addRow("Adet", self.batch_size)
        layout.addLayout(form)

        self.render_button = QPushButton("TEK TIKLA VARYANT OLUŞTUR")
        self.render_button.setMinimumHeight(48)
        self.render_button.clicked.connect(self.start_batch)
        layout.addWidget(self.render_button)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        outer.addWidget(panel)
        outer.addStretch()
        return page

    def choose_master(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Input video seç", "", "Video (*.mp4 *.mov *.mkv *.webm *.m4v)"
        )
        if path:
            source = Path(path).resolve()
            self.master.setText(str(source))
            if not self.output_dir.text().strip():
                self.output_dir.setText(str(source.parent / f"{source.stem}-variants"))

    def choose_output(self) -> None:
        initial = self.output_dir.text().strip() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Output klasörünü seç", initial)
        if selected:
            self.output_dir.setText(str(Path(selected).resolve()))

    def start_batch(self) -> None:
        source = Path(self.master.text().strip())
        if not source.is_file():
            QMessageBox.warning(self, "Input bulunamadı", "Geçerli bir video seçin")
            return
        output = Path(self.output_dir.text().strip()) if self.output_dir.text().strip() else source.parent / f"{source.stem}-variants"
        self.output_dir.setText(str(output.resolve()))
        self.render_button.setEnabled(False)
        self.progress.setValue(0)
        task = core.BackgroundTask(
            lambda signals: self.variant_engine.render(source, output, self.batch_size.value(), signals)
        )
        task.signals.log.connect(self.log)
        task.signals.progress.connect(self.progress.setValue)
        task.signals.result.connect(self._variant_done)
        task.signals.error.connect(lambda detail: QMessageBox.critical(self, "Üretim başarısız", detail))
        task.signals.finished.connect(lambda current=task: self._variant_finished(current))
        self.tasks.add(task)
        task.start()

    def start_render(self) -> None:
        self.start_batch()

    def _variant_done(self, outputs: object) -> None:
        self.last_outputs = list(outputs or [])
        QMessageBox.information(
            self, "Hazır", f"{len(self.last_outputs)} varyant oluşturuldu.\n{self.output_dir.text()}"
        )

    def _variant_finished(self, task: object) -> None:
        self.tasks.discard(task)
        self.render_button.setEnabled(True)

    def _api_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
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
        outer.addStretch()
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
