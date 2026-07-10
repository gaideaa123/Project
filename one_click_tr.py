from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import keyring
import requests
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

import app as core

MEDIA_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
GROK_SERVICE = "signaldesk-grok"
GROK_ENDPOINT = "https://api.x.ai/v1/chat/completions"


def media_files(path: Path) -> list[Path]:
    if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
        return [path.resolve()]
    if path.is_dir():
        return sorted(p.resolve() for p in path.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS)
    return []


def probe(path: Path) -> tuple[float, bool]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-show_entries", "stream=codec_type", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    duration = float(data.get("format", {}).get("duration") or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    if duration <= 0:
        raise RuntimeError(f"Video süresi okunamadı: {path.name}")
    return duration, has_audio


class GrokCaptionClient:
    def __init__(self, api_key: str, brief: str):
        self.api_key = api_key
        self.brief = brief.strip()

    def create(self, source: Path, variant_number: int) -> str:
        prompt = f"""Türkçe TikTok caption yaz. Sadece caption metnini döndür.
Stil: samimi, hızlı, merak uyandıran; 2 kısa cümle, 2-4 doğal emoji ve yeni satırda tam 5 alakalı hashtag.
Satış spam'i, yanıltıcı vaat ve aynı kalıbı tekrar etmek yok. 2200 karakteri aşma.
İçerik konusu: {self.brief or source.stem}
Varyant numarası: {variant_number}
Örnek ton: Ben o uzun uzun düşünmeyi bıraktım 🤯 artık başlık kısmı otomatik geliyor! Kendi zamanınızı geri alın. 💻 🚀
"""
        response = requests.post(
            GROK_ENDPOINT,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": os.environ.get("GROK_MODEL", "grok-3-mini"),
                "temperature": 0.95,
                "messages": [
                    {"role": "system", "content": "Sen yaratıcı ama dürüst bir Türkçe sosyal medya editörüsün."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=(15, 90),
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Grok JSON dönmedi (HTTP {response.status_code})") from exc
        if not response.ok:
            message = data.get("error", {}).get("message") or data.get("error") or "istek başarısız"
            raise RuntimeError(f"Grok hatası: {message}")
        caption = str(data["choices"][0]["message"]["content"]).strip()
        if not caption:
            raise RuntimeError("Grok boş caption döndürdü")
        return caption[:2200]


class VariantRenderer:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render(self, source: Path, number: int) -> Path:
        duration, has_audio = probe(source)
        rng = random.SystemRandom()
        speed = rng.uniform(0.985, 1.018)
        zoom = rng.uniform(1.005, 1.035)
        saturation = rng.uniform(0.98, 1.05)
        contrast = rng.uniform(0.99, 1.035)
        brightness = rng.uniform(-0.012, 0.012)
        trim = min(rng.uniform(0.0, 0.18), max(0.0, duration - 1.0))
        target = self.output_dir / f"{source.stem}-variant-{number:03d}-{uuid.uuid4().hex[:7]}.mp4"
        vf = (
            f"setpts=PTS/{speed:.6f},"
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            f"scale=iw*{zoom:.6f}:ih*{zoom:.6f},"
            "crop=1080:1920,"
            f"eq=saturation={saturation:.6f}:contrast={contrast:.6f}:brightness={brightness:.6f},"
            "unsharp=5:5:0.25:3:3:0.0,format=yuv420p"
        )
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{trim:.3f}", "-i", str(source),
                   "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf]
        if has_audio:
            command += ["-af", f"atempo={speed:.6f},loudnorm=I=-14:TP=-1.5:LRA=11"]
        command += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-profile:v", "high", "-level", "4.1",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
            "-map_metadata", "-1", "-metadata", f"variant={number}", str(target),
        ]
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or f"FFmpeg başarısız: {source.name}")
        return target


class PipelineWorker(QThread):
    progress = Signal(int)
    log = Signal(str)
    completed = Signal(int, str)
    failed = Signal(str)

    def __init__(self, registry: core.AtomicRegistry, account_id: str, sources: list[Path], count: int,
                 output_dir: Path, api_key: str, brief: str, privacy: str):
        super().__init__()
        self.registry = registry
        self.account_id = account_id
        self.sources = sources
        self.count = count
        self.output_dir = output_dir
        self.api_key = api_key
        self.brief = brief
        self.privacy = privacy

    def run(self) -> None:
        try:
            if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
                raise RuntimeError("FFmpeg ve FFprobe PATH üzerinde bulunamadı")
            renderer = VariantRenderer(self.output_dir)
            grok = GrokCaptionClient(self.api_key, self.brief)
            total = len(self.sources) * self.count
            queued = 0
            first_run = core.utc_now() + timedelta(minutes=2)
            for source in self.sources:
                for number in range(1, self.count + 1):
                    if self.isInterruptionRequested():
                        raise RuntimeError("İşlem kullanıcı tarafından durduruldu")
                    self.log.emit(f"Üretiliyor: {source.name} ({number}/{self.count})")
                    output = renderer.render(source, number)
                    self.log.emit(f"Grok caption yazıyor: {output.name}")
                    caption = grok.create(source, number)
                    run_at = first_run + timedelta(hours=23 * queued)
                    self.registry.add_job(self.account_id, str(output), caption, run_at, self.privacy)
                    queued += 1
                    self.log.emit(f"Kuyruğa alındı: {run_at.astimezone().strftime('%d.%m.%Y %H:%M')}")
                    self.progress.emit(round(queued * 100 / total))
            self.completed.emit(queued, str(self.output_dir))
        except Exception as exc:
            self.failed.emit(str(exc))


class OneClickWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SignalDesk Tek Tık Yayıncı")
        self.resize(760, 650)
        self.registry = core.AtomicRegistry(core.DATA_DIR / "pipeline_registry.json")
        self.worker: PipelineWorker | None = None
        self._build()
        self._load_profiles()

    def _build(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        title = QLabel("Tek tıkla üret, caption yaz, 23 saatte bir sırala")
        title.setStyleSheet("font-size: 22px; font-weight: 700; margin: 8px 0 14px")
        layout.addWidget(title)
        form = QFormLayout()
        self.source = QLineEdit()
        source_button = QPushButton("Video / klasör seç")
        source_button.clicked.connect(self.choose_source)
        source_row = QHBoxLayout(); source_row.addWidget(self.source, 1); source_row.addWidget(source_button)
        form.addRow("Kaynak", source_row)
        self.output = QLineEdit()
        output_button = QPushButton("Çıktı klasörü")
        output_button.clicked.connect(self.choose_output)
        output_row = QHBoxLayout(); output_row.addWidget(self.output, 1); output_row.addWidget(output_button)
        form.addRow("Çıktı", output_row)
        self.count = QSpinBox(); self.count.setRange(1, 100); self.count.setValue(3); self.count.setSuffix(" varyant / video")
        form.addRow("Adet", self.count)
        self.profile = QComboBox(); form.addRow("TikTok profili", self.profile)
        self.privacy = QComboBox(); self.privacy.addItem("Yalnızca ben", "SELF_ONLY"); self.privacy.addItem("Herkese açık", "PUBLIC_TO_EVERYONE")
        form.addRow("Gizlilik", self.privacy)
        self.grok_key = QLineEdit(); self.grok_key.setEchoMode(QLineEdit.Password); self.grok_key.setPlaceholderText("Grok API key")
        form.addRow("Grok API", self.grok_key)
        layout.addLayout(form)
        layout.addWidget(QLabel("İçerik konusu / caption briefi"))
        self.brief = QPlainTextEdit(); self.brief.setPlaceholderText("Örn: Yapay zekâ ile otomatik sosyal medya başlığı üreten site")
        self.brief.setMaximumHeight(90); layout.addWidget(self.brief)
        self.start = QPushButton("TEK TIKLA ÜRET VE KUYRUĞA AL")
        self.start.setMinimumHeight(52); self.start.clicked.connect(self.run_pipeline); layout.addWidget(self.start)
        self.progress = QProgressBar(); layout.addWidget(self.progress)
        self.logs = QPlainTextEdit(); self.logs.setReadOnly(True); layout.addWidget(self.logs, 1)
        self.setCentralWidget(root)

    def _load_profiles(self) -> None:
        self.profile.clear()
        for account in self.registry.snapshot().get("accounts", []):
            self.profile.addItem(account.get("name", "TikTok"), account["id"])
        saved = keyring.get_password(GROK_SERVICE, "api_key") or ""
        self.grok_key.setText(saved)

    def choose_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Video seç", "", "Video (*.mp4 *.mov *.m4v *.mkv *.webm)")
        if path:
            self.source.setText(path)
            if not self.output.text():
                p = Path(path); self.output.setText(str(p.parent / f"{p.stem}-variants"))

    def choose_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Çıktı klasörü")
        if path: self.output.setText(path)

    def run_pipeline(self) -> None:
        sources = media_files(Path(self.source.text().strip()))
        if not sources:
            QMessageBox.warning(self, "Kaynak yok", "Geçerli bir video seçin."); return
        if self.profile.currentIndex() < 0:
            QMessageBox.warning(self, "Profil yok", "Önce app_tr.py içinden TikTok profilini bağlayın."); return
        api_key = self.grok_key.text().strip()
        if not api_key:
            QMessageBox.warning(self, "Grok API yok", "Grok API key girin."); return
        output = Path(self.output.text().strip() or (sources[0].parent / "variants"))
        keyring.set_password(GROK_SERVICE, "api_key", api_key)
        self.start.setEnabled(False); self.progress.setValue(0); self.logs.clear()
        self.worker = PipelineWorker(
            self.registry, str(self.profile.currentData()), sources, self.count.value(), output,
            api_key, self.brief.toPlainText(), str(self.privacy.currentData()),
        )
        self.worker.progress.connect(self.progress.setValue)
        self.worker.log.connect(self.logs.appendPlainText)
        self.worker.failed.connect(self.on_failed)
        self.worker.completed.connect(self.on_completed)
        self.worker.finished.connect(lambda: self.start.setEnabled(True))
        self.worker.start()

    def on_failed(self, message: str) -> None:
        self.logs.appendPlainText(f"HATA: {message}")
        QMessageBox.critical(self, "İşlem durdu", message)

    def on_completed(self, count: int, folder: str) -> None:
        self.progress.setValue(100)
        QMessageBox.information(self, "Hazır", f"{count} video üretildi ve 23 saat arayla kuyruğa alındı.\n{folder}")


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = OneClickWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
