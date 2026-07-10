from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import ffmpeg
import keyring
from PySide6.QtCore import QLocale, QThread, Signal
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


def video_bilgisi(path: Path) -> tuple[float, bool]:
    data = ffmpeg.probe(str(path))
    duration = float(data.get("format", {}).get("duration") or 0)
    has_audio = any(stream.get("codec_type") == "audio" for stream in data.get("streams", []))
    if duration <= 0:
        raise RuntimeError(f"Video süresi okunamadı: {path.name}")
    return duration, has_audio


def _visual_chain(label: str, speed: float, zoom: float, saturation: float,
                  contrast: float, brightness: float, teaser: bool = False) -> str:
    timing = "setpts=PTS-STARTPTS" if teaser else f"setpts=(PTS-STARTPTS)/{speed:.6f}"
    return (
        f"[{label}:v]{timing},"
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        f"scale=iw*{zoom:.6f}:ih*{zoom:.6f},"
        "crop=1080:1920,"
        f"eq=saturation={saturation:.6f}:contrast={contrast:.6f}:brightness={brightness:.6f},"
        "unsharp=5:5:0.20:3:3:0.0,format=yuv420p"
    )


def varyant_uret(source: Path, output: Path, count: int, progress, status) -> list[str]:
    """Create editorial variants with an automatic teaser opening, never mirroring."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("FFmpeg ve FFprobe PATH üzerinde bulunamadı")
    if not source.is_file() or source.suffix.lower() not in MEDIA_EXTENSIONS:
        raise RuntimeError("Geçerli bir input video seçin")

    output.mkdir(parents=True, exist_ok=True)
    duration, has_audio = video_bilgisi(source)
    rng = random.SystemRandom()
    results: list[str] = []

    for index in range(count):
        speed = rng.uniform(0.992, 1.012)
        zoom = rng.uniform(1.006, 1.025)
        saturation = rng.uniform(0.98, 1.04)
        contrast = rng.uniform(0.99, 1.03)
        brightness = rng.uniform(-0.008, 0.008)
        trim = min(rng.uniform(0.0, 0.10), max(0.0, duration - 1.0))
        teaser_duration = min(rng.uniform(0.75, 1.20), max(0.35, duration * 0.15))
        safe_latest = max(0.0, duration - teaser_duration - 0.2)
        teaser_start = min(duration * rng.choice((0.28, 0.42, 0.58, 0.70)), safe_latest)
        target = output / f"{source.stem}-variant-{index + 1:03d}-{uuid.uuid4().hex[:7]}.mp4"

        teaser_chain = _visual_chain("0", 1.0, zoom + 0.012, saturation, contrast, brightness, True)
        main_chain = _visual_chain("1", speed, zoom, saturation, contrast, brightness, False)
        filter_parts = [
            f"{teaser_chain}[teaser_v]",
            f"{main_chain}[main_v]",
            "[teaser_v][main_v]concat=n=2:v=1:a=0[out_v]",
        ]
        if has_audio:
            filter_parts += [
                "[0:a]asetpts=PTS-STARTPTS,aresample=48000[teaser_a]",
                f"[1:a]asetpts=PTS-STARTPTS,atempo={speed:.6f},aresample=48000,"
                "loudnorm=I=-14:TP=-1.5:LRA=11[main_a]",
                "[teaser_a][main_a]concat=n=2:v=0:a=1[out_a]",
            ]

        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{teaser_start:.3f}", "-t", f"{teaser_duration:.3f}", "-i", str(source),
            "-ss", f"{trim:.3f}", "-i", str(source),
            "-filter_complex", ";".join(filter_parts),
            "-map", "[out_v]",
        ]
        if has_audio:
            command += ["-map", "[out_a]"]
        command += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p",
        ]
        if has_audio:
            command += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
        command += ["-movflags", "+faststart", "-map_metadata", "-1", str(target)]

        status(f"{index + 1}/{count}: otomatik cold-open + ana kurgu")
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or "FFmpeg üretimi başarısız")
        results.append(str(target.resolve()))
        progress(round((index + 1) * 100 / count))
    return results


class RenderWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, source: Path, output: Path, count: int, parent=None):
        super().__init__(parent)
        self.source = source
        self.output = output
        self.count = count

    def run(self) -> None:
        try:
            self.completed.emit(varyant_uret(
                self.source, self.output, self.count,
                self.progress.emit, self.status.emit,
            ))
        except Exception as exc:
            self.failed.emit(str(exc))


class TurkceAnaPencere(core.MainWindow):
    def build_ui(self) -> None:
        super().build_ui()
        self.setWindowTitle("SignalDesk Tek Tık Video")
        self.render_worker: RenderWorker | None = None
        self.tabs.insertTab(1, self._one_click_tab(), "Tek Tık Video")
        self.tabs.addTab(self._api_tab(), "API Ayarları")

    def _one_click_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(24, 24, 24, 24)
        title = QLabel("Input ve output seç, gerisini tek tıkla hallet")
        title.setStyleSheet("font-size: 20px; font-weight: 700")
        outer.addWidget(title)
        note = QLabel("Aynalama yok. Her varyant otomatik teaser açılışı ve yeniden kurgulanmış tempo kullanır.")
        note.setWordWrap(True)
        outer.addWidget(note)

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
        self.status_label = QLabel("Hazır")
        layout.addWidget(self.status_label)
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
        if self.render_worker is not None and self.render_worker.isRunning():
            return
        source = Path(self.master.text().strip())
        if not source.is_file():
            QMessageBox.warning(self, "Input bulunamadı", "Geçerli bir video seçin")
            return
        output = Path(self.output_dir.text().strip()) if self.output_dir.text().strip() else source.parent / f"{source.stem}-variants"
        self.output_dir.setText(str(output.resolve()))
        self.render_button.setEnabled(False)
        self.progress.setValue(0)
        self.status_label.setText("Başlatılıyor...")
        self.render_worker = RenderWorker(source, output, self.batch_size.value(), self)
        self.render_worker.progress.connect(self.progress.setValue)
        self.render_worker.status.connect(self.status_label.setText)
        self.render_worker.completed.connect(self._variant_done)
        self.render_worker.failed.connect(self._variant_failed)
        self.render_worker.finished.connect(self._variant_finished)
        self.render_worker.start()

    def start_render(self) -> None:
        self.start_batch()

    def _variant_done(self, outputs: object) -> None:
        self.last_outputs = list(outputs or [])
        self.status_label.setText(f"{len(self.last_outputs)} varyant hazır")
        QMessageBox.information(self, "Hazır", f"{len(self.last_outputs)} varyant oluşturuldu.\n{self.output_dir.text()}")

    def _variant_failed(self, message: str) -> None:
        self.status_label.setText("Hata")
        QMessageBox.critical(self, "Üretim başarısız", message)

    def _variant_finished(self) -> None:
        self.render_button.setEnabled(True)
        worker = self.render_worker
        self.render_worker = None
        if worker is not None:
            worker.deleteLater()

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
    qt = QApplication(sys.argv)
    qt.setApplicationName("SignalDesk Tek Tık Video")
    qt.setOrganizationName("SignalDesk")
    qt.setStyle("Fusion")
    QLocale.setDefault(QLocale(QLocale.Turkish, QLocale.Turkey))
    window = TurkceAnaPencere()
    window.show()
    return qt.exec()


if __name__ == "__main__":
    raise SystemExit(main())
