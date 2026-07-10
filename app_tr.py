from __future__ import annotations

import itertools
import os
import random
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import ffmpeg
import keyring
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

import app as core

AYAR_SERVISI = "signaldesk-agency-console.app-settings"
REDIRECT = "http://127.0.0.1:3455/callback/"
KAPSAMLAR = "user.info.basic,video.publish"
MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}

CEVIRI = {
    "Profiles": "Profil Yönetimi", "Accounts": "Profil Yönetimi",
    "Asset processing": "Yaratıcı Medya Merkezi", "Processing": "Yaratıcı Medya Merkezi",
    "Deployment queue": "Yayın Kuyruğu", "Scheduler": "Yayın Kuyruğu",
    "Connect an official channel": "Resmî bir kanal bağla",
    "Connected profiles": "Yetkilendirilmiş profiller",
    "Add profile": "Profil ekle", "Remove selected": "Seçileni kaldır",
    "Profile": "Profil", "Platform": "Platform", "Token": "Belirteç",
    "Last post": "Son yayın", "Added": "Eklenme",
    "Access token": "Erişim belirteci", "Refresh token": "Yenileme belirteci",
    "H.264 delivery batch": "Yaratıcı video varyantları",
    "Choose video": "Ana videoyu seç", "Select master": "Ana videoyu seç",
    "Render outputs": "Yaratıcı varyantları üret", "Start batch": "Yaratıcı varyantları üret",
    "Live operations log": "Üretim günlüğü", "Processing log": "Üretim günlüğü",
    "Browse": "Gözat", "Caption": "Açıklama", "Run at": "Yayın zamanı",
    "Repeat daily": "Her gün tekrarla", "Queue post": "Yayını kuyruğa ekle",
    "Posting pipeline": "23 saat korumalı yayın hattı",
    "Run due now": "Zamanı gelenleri çalıştır", "Video": "Medya",
    "Next deployment": "Sonraki çalışma", "Cadence": "Tekrar",
    "State": "Durum", "Publish ID": "Yayın kimliği", "READY": "HAZIR",
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


def media_files(path: Path) -> list[Path]:
    if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
        return [path.resolve()]
    if path.is_dir():
        return sorted(
            item.resolve() for item in path.iterdir()
            if item.is_file() and item.suffix.lower() in MEDIA_EXTENSIONS
        )
    return []


class CreativeVariantEngine:
    """Assembles genuinely different editorial cuts from licensed source assets."""

    def __init__(self, registry: Any, logger: Any):
        self.registry = registry
        self.logger = logger

    @staticmethod
    def duration(path: Path) -> float:
        probe = ffmpeg.probe(str(path))
        value = probe.get("format", {}).get("duration")
        if value:
            return max(0.1, float(value))
        streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
        if streams and streams[0].get("duration"):
            return max(0.1, float(streams[0]["duration"]))
        raise RuntimeError(f"Süre okunamadı: {path.name}")

    @staticmethod
    def has_audio(path: Path) -> bool:
        probe = ffmpeg.probe(str(path))
        return any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))

    @staticmethod
    def normalized(path: Path, duration: float, width: int = 1080, height: int = 1920):
        source = ffmpeg.input(str(path))
        video = (
            source.video
            .filter("trim", duration=duration)
            .filter("setpts", "PTS-STARTPTS")
            .filter("scale", width, height, force_original_aspect_ratio="decrease")
            .filter("pad", width, height, "(ow-iw)/2", "(oh-ih)/2", color="black")
            .filter("fps", fps=30)
            .filter("format", "yuv420p")
        )
        if CreativeVariantEngine.has_audio(path):
            audio = (
                source.audio
                .filter("atrim", duration=duration)
                .filter("asetpts", "PTS-STARTPTS")
                .filter("aresample", 48000)
                .filter("aformat", sample_fmts="fltp", channel_layouts="stereo")
            )
        else:
            audio = ffmpeg.input(
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                f="lavfi", t=duration,
            ).audio
        return video, audio

    @staticmethod
    def font_file() -> str | None:
        candidates = (
            Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arialbd.ttf",
            Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        )
        return next((str(path) for path in candidates if path.is_file()), None)

    def register(self, record: dict[str, Any]) -> None:
        def operation(state: dict[str, Any]) -> None:
            state.setdefault("creative_variants", []).append(record)
        self.registry.mutate(operation)

    def render(
        self, master_path: Path, hook_folder: Path, broll_folder: Path,
        ctas: list[str], output: Path, count: int, signals: Any,
    ) -> list[str]:
        if not shutil_which_ffmpeg():
            raise RuntimeError("FFmpeg ve FFprobe PATH üzerinde bulunamadı")
        masters = media_files(master_path)
        hooks = media_files(hook_folder)
        brolls = media_files(broll_folder)
        if not masters:
            raise RuntimeError("Ana video bulunamadı")
        if not hooks:
            raise RuntimeError("Hook klasöründe desteklenen video bulunamadı")
        if not brolls:
            raise RuntimeError("B-roll klasöründe desteklenen video bulunamadı")
        if not ctas:
            raise RuntimeError("En az bir CTA metni girin")
        output.mkdir(parents=True, exist_ok=True)

        combinations = list(itertools.product(masters, hooks, brolls, ctas))
        random.SystemRandom().shuffle(combinations)
        accounts = self.registry.snapshot().get("accounts", [])
        results: list[str] = []

        for index in range(count):
            master, hook, broll, cta = combinations[index % len(combinations)]
            hook_duration = min(5.0, self.duration(hook))
            main_duration = self.duration(master)
            broll_duration = min(5.0, self.duration(broll))
            total_duration = hook_duration + main_duration + broll_duration
            hook_v, hook_a = self.normalized(hook, hook_duration)
            main_v, main_a = self.normalized(master, main_duration)
            broll_v, broll_a = self.normalized(broll, broll_duration)
            joined = ffmpeg.concat(
                hook_v, hook_a, main_v, main_a, broll_v, broll_a,
                v=1, a=1, n=3,
            ).node
            video, audio = joined[0], joined[1]
            start = max(0.0, total_duration - 3.5)
            drawtext = {
                "text": cta,
                "fontsize": 58,
                "fontcolor": "white",
                "borderw": 3,
                "bordercolor": "black",
                "box": 1,
                "boxcolor": "black@0.55",
                "boxborderw": 24,
                "x": "(w-text_w)/2",
                "y": "h-text_h-180",
                "enable": f"between(t,{start:.3f},{total_duration:.3f})",
            }
            font = self.font_file()
            if font:
                drawtext["fontfile"] = font
            video = video.filter("drawtext", **drawtext)
            variant_id = uuid.uuid4().hex
            target = output / f"creative-{index + 1:03d}-{variant_id[:8]}.mp4"
            signals.log.emit(
                f"{index + 1}/{count}: {hook.name} + {master.name} + {broll.name} | CTA: {cta}"
            )
            pipeline = ffmpeg.output(
                video, audio, str(target),
                vcodec="libx264", acodec="aac", preset="medium", crf=21,
                pix_fmt="yuv420p", audio_bitrate="192k", ar=48000,
                movflags="+faststart", map_metadata=-1,
                **{"profile:v": "high", "level:v": "4.1"},
            )
            try:
                pipeline.global_args("-hide_banner", "-loglevel", "error").overwrite_output().run(
                    capture_stdout=True, capture_stderr=True
                )
            except ffmpeg.Error as exc:
                detail = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
                raise RuntimeError(f"FFmpeg üretimi başarısız: {detail}") from exc

            account_id = accounts[index % len(accounts)]["id"] if accounts else ""
            record = {
                "id": variant_id,
                "output_path": str(target.resolve()),
                "master_path": str(master),
                "hook_path": str(hook),
                "broll_path": str(broll),
                "cta": cta,
                "assigned_account_id": account_id,
                "queue_job_id": "",
                "status": "rendered",
                "created_at": core.to_iso(core.now_utc()),
            }
            self.register(record)
            results.append(str(target.resolve()))
            signals.progress.emit(round((index + 1) * 100 / count))
        return results


def shutil_which_ffmpeg() -> bool:
    import shutil
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class TurkceAnaPencere(core.MainWindow):
    def build_ui(self) -> None:
        super().build_ui()
        self.setWindowTitle("SignalDesk Ajans Paneli")
        self._discover_processing_widgets()
        self._add_creative_controls()
        self.tabs.addTab(self._api_tab(), "API Ayarları")
        self._translate()

    def _discover_processing_widgets(self) -> None:
        page = self.tabs.widget(1)
        edits = page.findChildren(QLineEdit)
        spins = page.findChildren(QSpinBox)
        bars = page.findChildren(QProgressBar)
        self.master = getattr(self, "master", getattr(self, "master_video", edits[0] if edits else None))
        self.batch_size = getattr(self, "batch_size", getattr(self, "variant_count", spins[0] if spins else None))
        self.progress = getattr(self, "progress", getattr(self, "render_progress", bars[0] if bars else None))
        if self.master is None or self.batch_size is None or self.progress is None:
            raise RuntimeError("Medya işleme kontrolleri yüklenemedi")
        self.batch_size.setRange(1, 100)
        self.batch_size.setSuffix(" varyant")

    def _processing_panel_layout(self):
        page = self.tabs.widget(1)
        frames = [frame for frame in page.findChildren(QFrame) if frame.layout()]
        return frames[0].layout() if frames else page.layout()

    def _folder_row(self, placeholder: str, callback):
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setClearButtonEnabled(True)
        button = QPushButton("Klasör seç")
        button.clicked.connect(callback)
        row = QHBoxLayout()
        row.addWidget(field, 1)
        row.addWidget(button)
        return field, row

    def _add_creative_controls(self) -> None:
        layout = self._processing_panel_layout()
        self.output_dir, output_row = self._folder_row("Çıktı klasörü", self.choose_output)
        self.hook_dir, hook_row = self._folder_row("Hook klipleri klasörü (3-5 saniye)", self.choose_hook_dir)
        self.broll_dir, broll_row = self._folder_row("B-roll klipleri klasörü", self.choose_broll_dir)
        self.cta_texts = QPlainTextEdit()
        self.cta_texts.setPlaceholderText("Her satıra bir CTA yazın\nŞimdi keşfet\nDetaylar profilde\nBugün başlayın")
        self.cta_texts.setMaximumHeight(110)
        insertion = max(2, layout.count() - 3)
        layout.insertWidget(insertion, QLabel("Yaratıcı kaynaklar"))
        layout.insertLayout(insertion + 1, hook_row)
        layout.insertLayout(insertion + 2, broll_row)
        layout.insertLayout(insertion + 3, output_row)
        layout.insertWidget(insertion + 4, QLabel("CTA metinleri (satır başına bir adet)"))
        layout.insertWidget(insertion + 5, self.cta_texts)
        self.creative_engine = CreativeVariantEngine(self.registry, self.logger)

    def _choose_dir(self, field: QLineEdit, title: str) -> None:
        initial = field.text().strip() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, title, initial, QFileDialog.ShowDirsOnly)
        if selected:
            field.setText(str(Path(selected).resolve()))

    def choose_hook_dir(self) -> None:
        self._choose_dir(self.hook_dir, "Hook klipleri klasörünü seç")

    def choose_broll_dir(self) -> None:
        self._choose_dir(self.broll_dir, "B-roll klipleri klasörünü seç")

    def choose_output(self) -> None:
        self._choose_dir(self.output_dir, "Çıktı klasörünü seç")

    def choose_master(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ana videoyu seç", "", "Medya (*.mp4 *.mov *.mkv *.webm *.m4v)")
        if path:
            source = Path(path).resolve()
            self.master.setText(str(source))
            if not self.output_dir.text().strip():
                self.output_dir.setText(str(source.parent / f"{source.stem}-creative"))

    def start_batch(self) -> None:
        ctas = [line.strip() for line in self.cta_texts.toPlainText().splitlines() if line.strip()]
        values = {
            "Ana video": self.master.text().strip(),
            "Hook klasörü": self.hook_dir.text().strip(),
            "B-roll klasörü": self.broll_dir.text().strip(),
            "Çıktı klasörü": self.output_dir.text().strip(),
        }
        missing = [name for name, value in values.items() if not value]
        if missing or not ctas:
            self.error("Eksik yaratıcı kaynak", ", ".join(missing + ([] if ctas else ["CTA metni"])))
            return
        source = Path(values["Ana video"])
        hooks = Path(values["Hook klasörü"])
        brolls = Path(values["B-roll klasörü"])
        output = Path(values["Çıktı klasörü"])
        count = self.batch_size.value()
        button = getattr(self, "render_button", None)
        if button:
            button.setEnabled(False)
        self.progress.setValue(0)
        task = core.BackgroundTask(
            lambda signals: self.creative_engine.render(source, hooks, brolls, ctas, output, count, signals)
        )
        task.signals.log.connect(self.log)
        task.signals.progress.connect(self.progress.setValue)
        task.signals.result.connect(self._creative_done)
        task.signals.error.connect(lambda detail: self.error("Yaratıcı üretim başarısız", detail))
        task.signals.finished.connect(lambda current=task: self._creative_task_finished(current))
        self.tasks.add(task)
        task.start()

    def start_render(self) -> None:
        self.start_batch()

    def _creative_done(self, outputs: object) -> None:
        self.last_outputs = list(outputs or [])
        queue_field = getattr(self, "queue_video", getattr(self, "schedule_video", None))
        if queue_field and self.last_outputs:
            queue_field.setText(self.last_outputs[0])
        self.log(f"{len(self.last_outputs)} yaratıcı varyant üretildi ve hesap kuyruklarına eşlendi")

    def _creative_task_finished(self, task: object) -> None:
        self.tasks.discard(task)
        button = getattr(self, "render_button", None)
        if button:
            button.setEnabled(True)

    def _api_tab(self) -> QWidget:
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0, 18, 0, 0)
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(28, 24, 28, 28)
        title = QLabel("TikTok API ve OAuth Ayarları")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
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
        row = QHBoxLayout()
        save = QPushButton("Ayarları güvenli kasaya kaydet")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_api)
        auth = QPushButton("Profil belirteçlerini al")
        auth.clicked.connect(self.open_oauth)
        row.addWidget(save)
        row.addWidget(auth)
        row.addStretch()
        layout.addLayout(row)
        outer.addWidget(panel, 1)
        return page

    def save_api(self, notify: bool = True) -> bool:
        data = {
            "client_key": self.client_key_field.text().strip(),
            "client_secret": self.client_secret_field.text().strip(),
            "redirect_uri": self.redirect_field.text().strip(),
            "scopes": self.scopes_field.text().strip(),
        }
        if not all(data.values()):
            QMessageBox.warning(self, "Eksik API ayarı", "Tüm API alanlarını doldurun.")
            return False
        for name, value in data.items():
            keyring.set_password(AYAR_SERVISI, name, value)
        ayarlari_yukle()
        if notify:
            QMessageBox.information(self, "Kaydedildi", "API ayarları güvenli kasaya kaydedildi.")
        return True

    def open_oauth(self) -> None:
        if not self.save_api(False):
            return
        helper = Path(__file__).with_name("oauth_helper.py")
        kwargs: dict[str, Any] = {"cwd": str(helper.parent), "env": os.environ.copy()}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
        subprocess.Popen([sys.executable, str(helper)], **kwargs)

    def _translate(self) -> None:
        for index, name in enumerate(("Profil Yönetimi", "Yaratıcı Medya Merkezi", "Yayın Kuyruğu", "API Ayarları")):
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
