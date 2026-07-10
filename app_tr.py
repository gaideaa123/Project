from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import uuid
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

AYAR_SERVISI = "signaldesk-agency-console.app-settings"
GROK_SERVISI = "signaldesk-grok"
GROK_URL = "https://api.x.ai/v1/chat/completions"
REDIRECT = "http://127.0.0.1:3455/callback/"
KAPSAMLAR = "user.info.basic,video.publish"
MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
DEFAULT_OUTPUT = Path(r"C:\Users\ahmet\Music\cikti")
CAPTION_HISTORY = core.DATA_DIR / "grok_caption_history.json"
DEFAULT_GUIDE = """Konu: Başlık üretmeyi kolaylaştıran faydalı bir internet sitesi.
Hedef kitle: teknoloji, yazılım, girişimcilik ve içerik üretimiyle ilgilenen Türkçe TikTok kullanıcıları.
Ton: doğal, merak uyandıran, enerjik, samimi ve güvenilir. Abartılı veya anlamsız vaat kullanma.
Biçim: iki kısa ve akıcı cümle, doğal yerleştirilmiş 2-4 emoji, yeni satırda tam 5 alakalı hashtag.
Dil: kusursuz Türkiye Türkçesi; anlatım bozukluğu, devrik ve yapay cümle, yazım veya noktalama hatası olmasın."""
EXAMPLES = [
    "Viral başlık yazmayı bırakıp bu siteyi denedim 🤯 İnanılmaz sonuçlara hazır olun. Kaydetmeyi unutmayın! 🖤 💻\n#teknoloji #başlık #viral #yazılım #internettavsiyeleri",
    "Kimse size başlıkların gücünden bahsetmiyor 🔥 Tüm oyunu değiştiren bir araç buldum, sonra teşekkür edersiniz! 👀 💻\n#websitesi #başlıkönerisi #teknolojisever #girişimcilik #fikir",
    "Neden en iyi başlıkları bulmak hep bu kadar zor? 🤔 Bu siteyle hepsi artık elimde. Deneyip yorumunuzu bırakın! 🌟 💻\n#başlıkönerisi #teknoloji #internet #araçlar #faydalı",
]


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
        "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
        f"scale=iw*{zoom:.6f}:ih*{zoom:.6f}:flags=lanczos,"
        "crop=1080:1920,"
        f"eq=saturation={saturation:.6f}:contrast={contrast:.6f}:brightness={brightness:.6f},"
        "unsharp=5:5:0.20:3:3:0.0,fps=30,settb=AVTB,setsar=1,format=yuv420p"
    )


def varyant_uret(source: Path, output: Path, count: int, progress, status) -> list[str]:
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
        target = output / f"{index + 1}.mp4"

        teaser_chain = _visual_chain("0", 1.0, zoom + 0.012, saturation, contrast, brightness, True)
        main_chain = _visual_chain("1", speed, zoom, saturation, contrast, brightness, False)
        filters = [
            f"{teaser_chain}[teaser_v]", f"{main_chain}[main_v]",
            "[teaser_v][main_v]concat=n=2:v=1:a=0[out_v]",
        ]
        if has_audio:
            filters += [
                "[0:a]asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,"
                "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[teaser_a]",
                f"[1:a]asetpts=PTS-STARTPTS,atempo={speed:.6f},"
                "aresample=48000:async=1:first_pts=0,"
                "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                "loudnorm=I=-14:TP=-1.5:LRA=11[main_a]",
                "[teaser_a][main_a]concat=n=2:v=0:a=1[out_a]",
            ]

        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{teaser_start:.3f}", "-t", f"{teaser_duration:.3f}", "-i", str(source),
            "-ss", f"{trim:.3f}", "-i", str(source),
            "-filter_complex", ";".join(filters), "-map", "[out_v]",
        ]
        if has_audio:
            command += ["-map", "[out_a]"]
        command += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-profile:v", "high",
            "-level", "4.1", "-pix_fmt", "yuv420p", "-r", "30", "-fps_mode", "cfr",
        ]
        if has_audio:
            command += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
        command += ["-movflags", "+faststart", "-map_metadata", "-1", "-shortest", str(target)]

        status(f"{index + 1}/{count}: {target.name} oluşturuluyor")
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode:
            target.unlink(missing_ok=True)
            raise RuntimeError(completed.stderr.strip() or "FFmpeg üretimi başarısız")
        if not target.exists() or target.stat().st_size == 0:
            target.unlink(missing_ok=True)
            raise RuntimeError("FFmpeg boş çıktı üretti")
        results.append(str(target.resolve()))
        progress(round((index + 1) * 100 / count))
    return results


def _normalize_caption(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip(" \"'")


def _load_caption_history() -> list[str]:
    try:
        data = json.loads(CAPTION_HISTORY.read_text(encoding="utf-8"))
        return [str(item) for item in data] if isinstance(data, list) else []
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def _save_caption_history(items: list[str]) -> None:
    CAPTION_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    temporary = CAPTION_HISTORY.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, CAPTION_HISTORY)


class GrokCaptionClient:
    def __init__(self, api_key: str, guide: str):
        self.api_key = api_key.strip()
        self.guide = guide.strip() or DEFAULT_GUIDE

    @staticmethod
    def _validate(caption: str) -> bool:
        lines = [line.strip() for line in caption.splitlines() if line.strip()]
        if len(lines) != 2 or len(caption) > 500:
            return False
        hashtags = re.findall(r"(?<!\w)#[\wçğıöşüÇĞİÖŞÜ]+", lines[1])
        if len(hashtags) != 5 or "#" in lines[0]:
            return False
        banned = ("başlık yazmayı bırakıp", "inanılmaz sonuçlara hazır olun")
        return not any(phrase in _normalize_caption(caption) for phrase in banned)

    def create_unique(self, profile_name: str, history: list[str]) -> str:
        known = {_normalize_caption(item) for item in history}
        recent = history[-80:]
        prompt = f"""Bir Türkçe TikTok caption editörüsün. Aşağıdaki rehbere harfiyen uy.

REHBER:
{self.guide}

KALİTE KURALLARI:
- Yalnızca nihai captionu döndür; açıklama, tırnak, başlık veya markdown ekleme.
- İlk satır 2 kısa, doğal ve anlamlı Türkçe cümleden oluşsun.
- İkinci satırda yalnızca tam 5 hashtag olsun.
- Emoji cümlenin anlamını desteklesin; rastgele emoji dizme.
- Aynı kelimeyi gereksiz tekrarlama; yapay çeviri dili ve anlatım bozukluğu kullanma.
- Ürün hakkında doğrulanmamış sonuç, garanti veya sahte deneyim iddiası yazma.
- Örneklerin ritmini öğren ama hiçbir cümleyi kopyalama.
- Daha önce kullanılan captionlara anlam ve kalıp olarak da benzemesin.

İYİ TON ÖRNEKLERİ:
{chr(10).join(EXAMPLES)}

PROFİL: {profile_name}
DAHA ÖNCE KULLANILANLAR:
{json.dumps(recent, ensure_ascii=False)}
"""
        for attempt in range(5):
            response = requests.post(
                GROK_URL,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": os.getenv("GROK_MODEL", "grok-4.3-latest"),
                    "temperature": min(1.0, 0.78 + attempt * 0.04),
                    "messages": [
                        {"role": "system", "content": "Kusursuz Türkiye Türkçesi kullanan kıdemli sosyal medya editörüsün."},
                        {"role": "user", "content": prompt + f"\nDeneme çeşitlilik kodu: {uuid.uuid4().hex}"},
                    ],
                },
                timeout=(15, 90),
            )
            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError(f"Grok geçersiz yanıt verdi (HTTP {response.status_code})") from exc
            if not response.ok:
                detail = payload.get("error", {})
                if isinstance(detail, dict):
                    detail = detail.get("message") or detail.get("code")
                raise RuntimeError(f"Grok API hatası: {detail or response.status_code}")
            caption = str(payload["choices"][0]["message"]["content"]).strip().strip("\"")
            normalized = _normalize_caption(caption)
            if normalized not in known and self._validate(caption):
                history.append(caption)
                _save_caption_history(history)
                return caption
        raise RuntimeError("Grok 5 denemede kurallara uyan benzersiz caption üretemedi")


class RenderWorker(QThread):
    progress = Signal(int); status = Signal(str); completed = Signal(object); failed = Signal(str)
    def __init__(self, source: Path, output: Path, count: int, parent=None):
        super().__init__(parent); self.source = source; self.output = output; self.count = count
    def run(self) -> None:
        try:
            self.completed.emit(varyant_uret(self.source, self.output, self.count, self.progress.emit, self.status.emit))
        except Exception as exc:
            self.failed.emit(str(exc))


class PublishWorker(QThread):
    status = Signal(str); completed = Signal(int); failed = Signal(str)
    def __init__(self, registry, assignments: list[tuple[dict[str, Any], Path]], api_key: str, guide: str, parent=None):
        super().__init__(parent)
        self.registry = registry; self.assignments = assignments; self.api_key = api_key; self.guide = guide
    def run(self) -> None:
        try:
            history = _load_caption_history()
            grok = GrokCaptionClient(self.api_key, self.guide)
            for index, (account, video) in enumerate(self.assignments, 1):
                self.status.emit(f"{account.get('name', 'Profil')}: Grok caption yazıyor")
                caption = grok.create_unique(account.get("name", "TikTok profil"), history)
                self.registry.add_job(account["id"], str(video), caption, core.utc_now(), "PUBLIC_TO_EVERYONE")
                self.status.emit(f"{index}/{len(self.assignments)} kuyruğa eklendi: {video.name}")
            self.completed.emit(len(self.assignments))
        except Exception as exc:
            self.failed.emit(str(exc))


class TurkceAnaPencere(core.MainWindow):
    def build_ui(self) -> None:
        super().build_ui()
        self.setWindowTitle("SignalDesk Tek Tık Video")
        self.render_worker: RenderWorker | None = None
        self.publish_worker: PublishWorker | None = None
        self.output_path = DEFAULT_OUTPUT
        self.tabs.insertTab(1, self._one_click_tab(), "Tek Tık Video")
        self.tabs.insertTab(2, self._grok_profiles_tab(), "Profiller + Grok")
        self.tabs.addTab(self._api_tab(), "API Ayarları")

    def _one_click_tab(self) -> QWidget:
        page = QWidget(); outer = QVBoxLayout(page); outer.setContentsMargins(24, 24, 24, 24)
        outer.addWidget(QLabel("Input seç, varyantları 1.mp4, 2.mp4, 3.mp4 diye sırala"))
        panel = QFrame(); layout = QVBoxLayout(panel); form = QFormLayout()
        self.master = QLineEdit(); self.master.setPlaceholderText("Input video")
        choose = QPushButton("Input seç"); choose.clicked.connect(self.choose_master)
        row = QHBoxLayout(); row.addWidget(self.master, 1); row.addWidget(choose); form.addRow("Input", row)
        self.output_dir = QLineEdit(str(DEFAULT_OUTPUT)); self.output_dir.setReadOnly(True)
        form.addRow("Output", self.output_dir)
        self.batch_size = QSpinBox(); self.batch_size.setRange(1, 100); self.batch_size.setValue(5); self.batch_size.setSuffix(" varyant")
        form.addRow("Adet", self.batch_size); layout.addLayout(form)
        self.render_button = QPushButton("TEK TIKLA VARYANT OLUŞTUR"); self.render_button.setMinimumHeight(48); self.render_button.clicked.connect(self.start_batch)
        layout.addWidget(self.render_button); self.progress = QProgressBar(); layout.addWidget(self.progress)
        self.status_label = QLabel("Hazır"); layout.addWidget(self.status_label); outer.addWidget(panel); outer.addStretch(); return page

    def _grok_profiles_tab(self) -> QWidget:
        page = QWidget(); outer = QVBoxLayout(page); outer.setContentsMargins(24, 24, 24, 24)
        outer.addWidget(QLabel("Profil sırasına göre 1.mp4, 2.mp4, 3.mp4 dağıtılır"))
        toolbar = QHBoxLayout()
        select_all = QPushButton("Hepsini seç"); select_all.clicked.connect(self.select_all_profiles)
        publish_all = QPushButton("SEÇİLENLERE GROK CAPTION ÜRET VE PAYLAŞ"); publish_all.clicked.connect(self.publish_selected)
        toolbar.addWidget(select_all); toolbar.addWidget(publish_all); toolbar.addStretch(); outer.addLayout(toolbar)
        self.profile_table = QTableWidget(0, 4); self.profile_table.setHorizontalHeaderLabels(["Seç", "Profil", "Video", "İşlem"])
        self.profile_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        outer.addWidget(self.profile_table)
        self.publish_status = QLabel("Hazır"); outer.addWidget(self.publish_status)
        self.refresh_grok_profiles(); return page

    def _api_tab(self) -> QWidget:
        page = QWidget(); outer = QVBoxLayout(page); panel = QFrame(); layout = QVBoxLayout(panel); form = QFormLayout()
        self.client_key_field = QLineEdit(kasa_oku("client_key")); self.client_secret_field = QLineEdit(kasa_oku("client_secret")); self.client_secret_field.setEchoMode(QLineEdit.Password)
        self.redirect_field = QLineEdit(kasa_oku("redirect_uri", REDIRECT)); self.scopes_field = QLineEdit(kasa_oku("scopes", KAPSAMLAR)
        )
        self.grok_key_field = QLineEdit(keyring.get_password(GROK_SERVISI, "api_key") or ""); self.grok_key_field.setEchoMode(QLineEdit.Password)
        form.addRow("TikTok Client Key", self.client_key_field); form.addRow("TikTok Client Secret", self.client_secret_field)
        form.addRow("Redirect URI", self.redirect_field); form.addRow("OAuth kapsamları", self.scopes_field); form.addRow("Grok API Key", self.grok_key_field)
        layout.addLayout(form); layout.addWidget(QLabel("Grok caption rehberi"))
        self.grok_guide = QPlainTextEdit(keyring.get_password(GROK_SERVISI, "guide") or DEFAULT_GUIDE); self.grok_guide.setMinimumHeight(180); layout.addWidget(self.grok_guide)
        save = QPushButton("TÜM API AYARLARINI GÜVENLİ KASAYA KAYDET"); save.clicked.connect(self.save_api); layout.addWidget(save)
        outer.addWidget(panel); outer.addStretch(); return page

    def refresh_grok_profiles(self) -> None:
        if not hasattr(self, "profile_table"):
            return
        accounts = self.registry.snapshot().get("accounts", [])
        self.profile_table.setRowCount(len(accounts))
        for row, account in enumerate(accounts):
            check = QCheckBox(); self.profile_table.setCellWidget(row, 0, check)
            self.profile_table.setItem(row, 1, QTableWidgetItem(account.get("name", "TikTok")))
            self.profile_table.setItem(row, 2, QTableWidgetItem(f"{row + 1}.mp4"))
            button = QPushButton("Grok caption oluşturup yükle")
            button.clicked.connect(lambda _=False, r=row: self.publish_one(r))
            self.profile_table.setCellWidget(row, 3, button)

    def select_all_profiles(self) -> None:
        for row in range(self.profile_table.rowCount()):
            check = self.profile_table.cellWidget(row, 0)
            if isinstance(check, QCheckBox): check.setChecked(True)

    def _account_rows(self) -> list[dict[str, Any]]:
        return self.registry.snapshot().get("accounts", [])

    def publish_one(self, row: int) -> None:
        accounts = self._account_rows()
        if row >= len(accounts):
            QMessageBox.warning(self, "Profil yok", "Profil listesi değişti; ekranı yenileyin"); return
        self._start_publish([(accounts[row], self.output_path / f"{row + 1}.mp4")])

    def publish_selected(self) -> None:
        accounts = self._account_rows(); selected = []
        for row, account in enumerate(accounts):
            check = self.profile_table.cellWidget(row, 0)
            if isinstance(check, QCheckBox) and check.isChecked():
                selected.append(account)
        assignments = [(account, self.output_path / f"{index + 1}.mp4") for index, account in enumerate(selected)]
        self._start_publish(assignments)

    def _start_publish(self, assignments: list[tuple[dict[str, Any], Path]]) -> None:
        if self.publish_worker is not None and self.publish_worker.isRunning():
            return
        if not assignments:
            QMessageBox.warning(self, "Profil seçilmedi", "En az bir profil seçin"); return
        missing = [str(video) for _, video in assignments if not video.is_file()]
        if missing:
            QMessageBox.warning(self, "Video eksik", "Önce varyantları oluşturun:\n" + "\n".join(missing)); return
        api_key = self.grok_key_field.text().strip()
        if not api_key:
            QMessageBox.warning(self, "Grok API eksik", "API Ayarları sekmesinden Grok API key girin"); return
        keyring.set_password(GROK_SERVISI, "api_key", api_key)
        keyring.set_password(GROK_SERVISI, "guide", self.grok_guide.toPlainText().strip())
        self.publish_worker = PublishWorker(self.registry, assignments, api_key, self.grok_guide.toPlainText(), self)
        self.publish_worker.status.connect(self.publish_status.setText)
        self.publish_worker.completed.connect(self._publish_ready)
        self.publish_worker.failed.connect(self._publish_failed)
        self.publish_worker.finished.connect(self._publish_finished)
        self.publish_worker.start()

    def _publish_ready(self, count: int) -> None:
        self.publish_status.setText(f"{count} yayın kuyruğa alındı")
        QTimer.singleShot(100, self.run_due)
        QMessageBox.information(self, "Yayın başladı", f"{count} profile benzersiz Grok caption ve video atandı")

    def _publish_failed(self, message: str) -> None:
        self.publish_status.setText("Hata"); QMessageBox.critical(self, "Dağıtım başarısız", message)

    def _publish_finished(self) -> None:
        worker = self.publish_worker; self.publish_worker = None
        if worker is not None: worker.deleteLater()

    def choose_master(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Input video seç", "", "Video (*.mp4 *.mov *.mkv *.webm *.m4v)")
        if path: self.master.setText(str(Path(path).resolve()))

    def start_batch(self) -> None:
        if self.render_worker is not None and self.render_worker.isRunning(): return
        source = Path(self.master.text().strip())
        if not source.is_file(): QMessageBox.warning(self, "Input bulunamadı", "Geçerli bir video seçin"); return
        self.output_path = DEFAULT_OUTPUT; self.output_path.mkdir(parents=True, exist_ok=True)
        self.render_button.setEnabled(False); self.progress.setValue(0); self.status_label.setText("Başlatılıyor...")
        self.render_worker = RenderWorker(source, self.output_path, self.batch_size.value(), self)
        self.render_worker.progress.connect(self.progress.setValue); self.render_worker.status.connect(self.status_label.setText)
        self.render_worker.completed.connect(self._variant_done); self.render_worker.failed.connect(self._variant_failed); self.render_worker.finished.connect(self._variant_finished)
        self.render_worker.start()

    def start_render(self) -> None: self.start_batch()
    def _variant_done(self, outputs: object) -> None:
        self.last_outputs = list(outputs or []); self.status_label.setText(f"{len(self.last_outputs)} varyant hazır"); self.refresh_grok_profiles()
        QMessageBox.information(self, "Hazır", f"{len(self.last_outputs)} varyant oluşturuldu.\n{self.output_path}")
    def _variant_failed(self, message: str) -> None: self.status_label.setText("Hata"); QMessageBox.critical(self, "Üretim başarısız", message)
    def _variant_finished(self) -> None:
        self.render_button.setEnabled(True); worker = self.render_worker; self.render_worker = None
        if worker is not None: worker.deleteLater()

    def save_api(self) -> None:
        data = {"client_key": self.client_key_field.text().strip(), "client_secret": self.client_secret_field.text().strip(), "redirect_uri": self.redirect_field.text().strip(), "scopes": self.scopes_field.text().strip()}
        if not all(data.values()) or not self.grok_key_field.text().strip():
            QMessageBox.warning(self, "Eksik API ayarı", "TikTok ve Grok alanlarını doldurun"); return
        for name, value in data.items(): keyring.set_password(AYAR_SERVISI, name, value)
        keyring.set_password(GROK_SERVISI, "api_key", self.grok_key_field.text().strip()); keyring.set_password(GROK_SERVISI, "guide", self.grok_guide.toPlainText().strip())
        ayarlari_yukle(); QMessageBox.information(self, "Kaydedildi", "TikTok ve Grok ayarları güvenli kasaya kaydedildi")


def main() -> int:
    ayarlari_yukle(); qt = QApplication(sys.argv); qt.setApplicationName("SignalDesk Tek Tık Video"); qt.setOrganizationName("SignalDesk"); qt.setStyle("Fusion")
    QLocale.setDefault(QLocale(QLocale.Turkish, QLocale.Turkey)); window = TurkceAnaPencere(); window.show(); return qt.exec()


if __name__ == "__main__": raise SystemExit(main())
