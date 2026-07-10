from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import ffmpeg
import keyring
import requests
from PySide6.QtCore import QLocale, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import app as core

TIKTOK_SERVICE = "signaldesk-agency-console.app-settings"
AZURE_SERVICE = "signaldesk-azure-gpt4o"
AZURE_DEFAULT_URL = (
    "https://yedekhesap145566-4746-resource.cognitiveservices.azure.com/"
    "openai/deployments/gpt-4o/chat/completions?api-version=2025-01-01-preview"
)
REDIRECT = "http://127.0.0.1:3455/callback/"
SCOPES = "user.info.basic,video.publish"
DEFAULT_OUTPUT = Path(r"C:\Users\ahmet\Music\cikti")
HISTORY_FILE = core.DATA_DIR / "azure_caption_history.json"
MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
GUIDE = """Konu: Başlık üretmeyi kolaylaştıran faydalı bir internet sitesi.
Hedef kitle: teknoloji, yazılım, girişimcilik ve içerik üretimiyle ilgilenen Türkçe TikTok kullanıcıları.
Ton: doğal, merak uyandıran, enerjik, samimi ve güvenilir.
Biçim: iki kısa ve akıcı cümle, doğal 2-4 emoji, ikinci satırda tam 5 alakalı hashtag.
Dil: kusursuz Türkiye Türkçesi. Anlatım bozukluğu, yapay çeviri, yazım ve noktalama hatası olmasın.
Doğrulanmamış sonuç, garanti, sahte deneyim ve abartılı vaat yazma."""
EXAMPLES = (
    "Viral başlık yazmayı bırakıp bu siteyi denedim 🤯 İyi bir fikir bulmak artık çok daha hızlı. Kaydetmeyi unutmayın! 🖤 💻\n#teknoloji #başlık #viral #yazılım #internettavsiyeleri",
    "Kimse size başlıkların gücünden bahsetmiyor 🔥 İşinizi kolaylaştıran bir araç buldum, mutlaka göz atın! 👀 💻\n#websitesi #başlıkönerisi #teknolojisever #girişimcilik #fikir",
    "Neden iyi bir başlık bulmak hep bu kadar zor? 🤔 Bu araç seçenekleri saniyeler içinde önünüze getiriyor. Deneyip yorumunuzu bırakın! 🌟 💻\n#başlıkönerisi #teknoloji #internet #araçlar #faydalı",
)


def vault_get(service: str, name: str, default: str = "") -> str:
    try:
        return keyring.get_password(service, name) or default
    except Exception:
        return default


def load_tiktok_settings() -> None:
    values = {
        "TIKTOK_CLIENT_KEY": vault_get(TIKTOK_SERVICE, "client_key"),
        "TIKTOK_CLIENT_SECRET": vault_get(TIKTOK_SERVICE, "client_secret"),
        "TIKTOK_REDIRECT_URI": vault_get(TIKTOK_SERVICE, "redirect_uri", REDIRECT),
        "TIKTOK_SCOPES": vault_get(TIKTOK_SERVICE, "scopes", SCOPES),
    }
    for name, value in values.items():
        if value:
            os.environ[name] = value


def normalize_caption(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip(" \"'")


def load_history() -> list[str]:
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return [str(item) for item in data] if isinstance(data, list) else []
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def save_history(items: list[str]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = HISTORY_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(items[-1000:], ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, HISTORY_FILE)


class AzureCaptionClient:
    def __init__(self, api_key: str, api_url: str, guide: str):
        self.api_key = api_key.strip()
        self.api_url = api_url.strip()
        self.guide = guide.strip() or GUIDE
        if not self.api_key:
            raise RuntimeError("Azure GPT-4o API anahtarı boş")
        if not self.api_url.startswith("https://") or "/chat/completions" not in self.api_url:
            raise RuntimeError("Azure GPT-4o API URL geçersiz")

    @staticmethod
    def valid(caption: str) -> bool:
        lines = [line.strip() for line in caption.splitlines() if line.strip()]
        if len(lines) != 2 or len(caption) > 500 or "#" in lines[0]:
            return False
        tags = re.findall(r"(?<!\w)#[\wçğıöşüÇĞİÖŞÜ]+", lines[1])
        return len(tags) == 5

    def create_unique(self, profile_name: str, history: list[str]) -> str:
        known = {normalize_caption(item) for item in history}
        prompt = f"""Aşağıdaki rehbere uyan Türkçe TikTok captionu yaz.

REHBER:
{self.guide}

KURALLAR:
- Yalnız nihai captionu döndür. Tırnak, markdown veya açıklama ekleme.
- İlk satır iki kısa, doğal, anlamlı Türkçe cümle olsun.
- İkinci satır yalnızca tam 5 alakalı hashtag içersin.
- 2-4 doğal emoji kullan; rastgele emoji dizme.
- Dil bilgisi, yazım ve noktalama kusursuz olsun.
- Örneklerin ritmini öğren ama kelimelerini ve cümlelerini kopyalama.
- Geçmiş captionlara hem cümle hem fikir kalıbı olarak benzeme.

İYİ TON ÖRNEKLERİ:
{chr(10).join(EXAMPLES)}

PROFİL: {profile_name}
SON KULLANILAN CAPTIONLAR:
{json.dumps(history[-100:], ensure_ascii=False)}
"""
        for attempt in range(5):
            response = requests.post(
                self.api_url,
                headers={"api-key": self.api_key, "Content-Type": "application/json"},
                json={
                    "temperature": min(1.0, 0.75 + attempt * 0.05),
                    "messages": [
                        {"role": "system", "content": "Kusursuz Türkiye Türkçesi kullanan kıdemli sosyal medya editörüsün."},
                        {"role": "user", "content": prompt + f"\nÇeşitlilik numarası: {random.SystemRandom().randrange(10**12)}"},
                    ],
                },
                timeout=(15, 90),
            )
            try:
                data = response.json()
            except ValueError as exc:
                raise RuntimeError(f"Azure GPT-4o geçersiz JSON döndürdü (HTTP {response.status_code})") from exc
            if not response.ok:
                error = data.get("error", {})
                detail = error.get("message") if isinstance(error, dict) else str(error)
                raise RuntimeError(f"Azure GPT-4o API hatası: {detail or response.status_code}")
            caption = str(data["choices"][0]["message"]["content"]).strip().strip("\"")
            if self.valid(caption) and normalize_caption(caption) not in known:
                history.append(caption)
                save_history(history)
                return caption
        raise RuntimeError("Azure GPT-4o, 5 denemede kurallara uyan benzersiz caption üretemedi")


def probe(path: Path) -> tuple[float, bool]:
    data = ffmpeg.probe(str(path))
    duration = float(data.get("format", {}).get("duration") or 0)
    audio = any(stream.get("codec_type") == "audio" for stream in data.get("streams", []))
    if duration <= 0:
        raise RuntimeError(f"Video süresi okunamadı: {path.name}")
    return duration, audio


def visual_chain(label: str, speed: float, zoom: float, teaser: bool) -> str:
    timing = "setpts=PTS-STARTPTS" if teaser else f"setpts=(PTS-STARTPTS)/{speed:.6f}"
    return (
        f"[{label}:v]{timing},scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
        f"scale=iw*{zoom:.6f}:ih*{zoom:.6f}:flags=lanczos,crop=1080:1920,"
        "fps=30,settb=AVTB,setsar=1,format=yuv420p"
    )


def render_variants(source: Path, output: Path, count: int, progress, status) -> list[str]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("FFmpeg ve FFprobe PATH üzerinde bulunamadı")
    duration, has_audio = probe(source)
    output.mkdir(parents=True, exist_ok=True)
    rng = random.SystemRandom()
    results: list[str] = []
    for index in range(count):
        speed = rng.uniform(0.992, 1.012)
        zoom = rng.uniform(1.006, 1.025)
        teaser_duration = min(rng.uniform(0.75, 1.20), max(0.35, duration * 0.15))
        teaser_start = min(duration * rng.choice((0.28, 0.42, 0.58, 0.70)), max(0.0, duration - teaser_duration - 0.2))
        target = output / f"{index + 1}.mp4"
        filters = [
            f"{visual_chain('0', 1.0, zoom + 0.012, True)}[tv]",
            f"{visual_chain('1', speed, zoom, False)}[mv]",
            "[tv][mv]concat=n=2:v=1:a=0[outv]",
        ]
        if has_audio:
            filters += [
                "[0:a]asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[ta]",
                f"[1:a]asetpts=PTS-STARTPTS,atempo={speed:.6f},aresample=48000:async=1:first_pts=0,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,loudnorm=I=-14:TP=-1.5:LRA=11[ma]",
                "[ta][ma]concat=n=2:v=0:a=1[outa]",
            ]
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{teaser_start:.3f}", "-t", f"{teaser_duration:.3f}", "-i", str(source), "-i", str(source), "-filter_complex", ";".join(filters), "-map", "[outv]"]
        if has_audio:
            command += ["-map", "[outa]"]
        command += ["-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30"]
        if has_audio:
            command += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
        command += ["-movflags", "+faststart", "-map_metadata", "-1", "-shortest", str(target)]
        status(f"{index + 1}/{count}: {target.name} oluşturuluyor")
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            target.unlink(missing_ok=True)
            raise RuntimeError(result.stderr.strip() or "FFmpeg üretimi başarısız")
        results.append(str(target.resolve()))
        progress(round((index + 1) * 100 / count))
    return results


class RenderWorker(QThread):
    progress = Signal(int); status = Signal(str); completed = Signal(object); failed = Signal(str)
    def __init__(self, source: Path, count: int, parent=None):
        super().__init__(parent); self.source = source; self.count = count
    def run(self) -> None:
        try:
            self.completed.emit(render_variants(self.source, DEFAULT_OUTPUT, self.count, self.progress.emit, self.status.emit))
        except Exception as exc:
            self.failed.emit(str(exc))


class PublishWorker(QThread):
    status = Signal(str); completed = Signal(int); failed = Signal(str)
    def __init__(self, registry, assignments, key: str, url: str, guide: str, parent=None):
        super().__init__(parent); self.registry = registry; self.assignments = assignments; self.key = key; self.url = url; self.guide = guide
    def run(self) -> None:
        try:
            history = load_history(); client = AzureCaptionClient(self.key, self.url, self.guide)
            for index, (account, video) in enumerate(self.assignments, 1):
                self.status.emit(f"{account.get('name', 'Profil')}: Azure GPT-4o caption yazıyor")
                caption = client.create_unique(account.get("name", "TikTok profil"), history)
                self.registry.add_job(account["id"], str(video), caption, core.utc_now(), "PUBLIC_TO_EVERYONE")
                self.status.emit(f"{index}/{len(self.assignments)} kuyruğa eklendi: {video.name}")
            self.completed.emit(len(self.assignments))
        except Exception as exc:
            self.failed.emit(str(exc))


class TurkceAnaPencere(core.MainWindow):
    def build_ui(self) -> None:
        super().build_ui()
        self.setWindowTitle("SignalDesk Azure GPT-4o Yayıncı")
        self.render_worker = None; self.publish_worker = None
        self.tabs.insertTab(1, self.video_tab(), "Tek Tık Video")
        self.tabs.insertTab(2, self.profiles_tab(), "Profiller + Azure GPT-4o")
        self.tabs.addTab(self.api_tab(), "API Ayarları")

    def video_tab(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page); form = QFormLayout()
        self.master = QLineEdit(); choose = QPushButton("Input seç"); choose.clicked.connect(self.choose_master)
        row = QHBoxLayout(); row.addWidget(self.master); row.addWidget(choose); form.addRow("Input", row)
        self.output = QLineEdit(str(DEFAULT_OUTPUT)); self.output.setReadOnly(True); form.addRow("Output", self.output)
        self.count = QSpinBox(); self.count.setRange(1, 100); self.count.setValue(5); form.addRow("Adet", self.count)
        layout.addLayout(form); self.render_button = QPushButton("VARYANTLARI OLUŞTUR"); self.render_button.clicked.connect(self.render)
        layout.addWidget(self.render_button); self.progress = QProgressBar(); layout.addWidget(self.progress); self.render_status = QLabel("Hazır"); layout.addWidget(self.render_status); layout.addStretch(); return page

    def profiles_tab(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page); row = QHBoxLayout()
        select = QPushButton("Hepsini seç"); select.clicked.connect(self.select_all)
        publish = QPushButton("SEÇİLENLERE AZURE GPT-4O CAPTION ÜRET VE PAYLAŞ"); publish.clicked.connect(self.publish_selected)
        row.addWidget(select); row.addWidget(publish); row.addStretch(); layout.addLayout(row)
        self.profile_table = QTableWidget(0, 4); self.profile_table.setHorizontalHeaderLabels(["Seç", "Profil", "Video", "İşlem"]); self.profile_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.profile_table); self.publish_status = QLabel("Hazır"); layout.addWidget(self.publish_status); self.refresh_profiles(); return page

    def api_tab(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page); form = QFormLayout()
        self.azure_key = QLineEdit(vault_get(AZURE_SERVICE, "api_key")); self.azure_key.setEchoMode(QLineEdit.Password)
        self.azure_url = QLineEdit(vault_get(AZURE_SERVICE, "api_url", AZURE_DEFAULT_URL))
        form.addRow("Azure GPT-4o API Key", self.azure_key); form.addRow("Azure GPT-4o API URL", self.azure_url); layout.addLayout(form)
        layout.addWidget(QLabel("Azure GPT-4o caption rehberi")); self.guide = QPlainTextEdit(vault_get(AZURE_SERVICE, "guide", GUIDE)); layout.addWidget(self.guide)
        save = QPushButton("AZURE AYARLARINI GÜVENLİ KASAYA KAYDET"); save.clicked.connect(self.save_azure); layout.addWidget(save); return page

    def refresh_profiles(self) -> None:
        accounts = self.registry.snapshot().get("accounts", []); self.profile_table.setRowCount(len(accounts))
        for row, account in enumerate(accounts):
            self.profile_table.setCellWidget(row, 0, QCheckBox()); self.profile_table.setItem(row, 1, QTableWidgetItem(account.get("name", "TikTok"))); self.profile_table.setItem(row, 2, QTableWidgetItem(f"{row + 1}.mp4"))
            button = QPushButton("Azure GPT-4o caption oluşturup yükle"); button.clicked.connect(lambda _=False, r=row: self.publish_rows([r])); self.profile_table.setCellWidget(row, 3, button)

    def select_all(self) -> None:
        for row in range(self.profile_table.rowCount()): self.profile_table.cellWidget(row, 0).setChecked(True)
    def publish_selected(self) -> None:
        self.publish_rows([row for row in range(self.profile_table.rowCount()) if self.profile_table.cellWidget(row, 0).isChecked()])
    def publish_rows(self, rows: list[int]) -> None:
        accounts = self.registry.snapshot().get("accounts", []); assignments = [(accounts[row], DEFAULT_OUTPUT / f"{row + 1}.mp4") for row in rows if row < len(accounts)]
        if not assignments: QMessageBox.warning(self, "Profil seçilmedi", "En az bir profil seçin"); return
        missing = [str(video) for _, video in assignments if not video.is_file()]
        if missing: QMessageBox.warning(self, "Video eksik", "Önce varyantları oluşturun:\n" + "\n".join(missing)); return
        self.save_azure(False); self.publish_worker = PublishWorker(self.registry, assignments, self.azure_key.text(), self.azure_url.text(), self.guide.toPlainText(), self)
        self.publish_worker.status.connect(self.publish_status.setText); self.publish_worker.completed.connect(self.publish_done); self.publish_worker.failed.connect(lambda message: QMessageBox.critical(self, "Azure GPT-4o hatası", message)); self.publish_worker.start()
    def publish_done(self, count: int) -> None:
        self.publish_status.setText(f"{count} yayın kuyruğa alındı"); QTimer.singleShot(100, self.run_due)

    def choose_master(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Input video seç", "", "Video (*.mp4 *.mov *.mkv *.webm *.m4v)")
        if path: self.master.setText(path)
    def render(self) -> None:
        source = Path(self.master.text().strip())
        if not source.is_file(): QMessageBox.warning(self, "Input yok", "Geçerli video seçin"); return
        self.render_button.setEnabled(False); self.render_worker = RenderWorker(source, self.count.value(), self); self.render_worker.progress.connect(self.progress.setValue); self.render_worker.status.connect(self.render_status.setText); self.render_worker.completed.connect(self.render_done); self.render_worker.failed.connect(lambda message: QMessageBox.critical(self, "FFmpeg hatası", message)); self.render_worker.finished.connect(lambda: self.render_button.setEnabled(True)); self.render_worker.start()
    def render_done(self, outputs: object) -> None:
        self.last_outputs = list(outputs or []); self.render_status.setText(f"{len(self.last_outputs)} varyant hazır"); self.refresh_profiles()
    def save_azure(self, notify: bool = True) -> None:
        if not self.azure_key.text().strip() or not self.azure_url.text().strip():
            if notify: QMessageBox.warning(self, "Eksik Azure ayarı", "API key ve URL girin")
            return
        keyring.set_password(AZURE_SERVICE, "api_key", self.azure_key.text().strip()); keyring.set_password(AZURE_SERVICE, "api_url", self.azure_url.text().strip()); keyring.set_password(AZURE_SERVICE, "guide", self.guide.toPlainText().strip())
        if notify: QMessageBox.information(self, "Kaydedildi", "Azure GPT-4o ayarları kaydedildi")


def main() -> int:
    load_tiktok_settings(); qt = QApplication(sys.argv); qt.setStyle("Fusion"); QLocale.setDefault(QLocale(QLocale.Turkish, QLocale.Turkey)); window = TurkceAnaPencere(); window.show(); return qt.exec()


if __name__ == "__main__": raise SystemExit(main())
