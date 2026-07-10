from __future__ import annotations

import copy
import json
import logging
import math
import os
import shutil
import sys
import tempfile
import threading
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import ffmpeg
import keyring
import requests
from platformdirs import user_data_dir
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateTimeEdit, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

APP_NAME = "SignalDesk Publisher"
APP_SLUG = "signaldesk-publisher"
KEYRING_SERVICE = "signaldesk-publisher.tokens"
TIKTOK_API = "https://open.tiktokapis.com"
POST_WINDOW = timedelta(hours=23)
UTC = timezone.utc


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def setup_logger(folder: Path) -> logging.Logger:
    folder.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(APP_SLUG)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        file_handler = logging.FileHandler(folder / "signaldesk.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    return logger


class RegistryError(RuntimeError):
    pass


class PipelineRegistry:
    """Atomic, thread-safe state with deterministic 23-hour scheduling guards."""

    def __init__(self, path: Path):
        self.path = path
        self.backup = path.with_suffix(path.suffix + ".bak")
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"version": 2, "accounts": [], "jobs": []})

    def _read(self) -> dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:
            if self.backup.exists():
                with self.backup.open("r", encoding="utf-8") as handle:
                    data = json.load(handle)
            else:
                raise RegistryError(f"Cannot read registry: {exc}") from exc
        if not isinstance(data.get("accounts"), list) or not isinstance(data.get("jobs"), list):
            raise RegistryError("Registry schema is invalid")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix="pipeline-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            if self.path.exists():
                shutil.copy2(self.path, self.backup)
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self._read())

    def mutate(self, operation: Callable[[dict[str, Any]], Any]) -> Any:
        with self.lock:
            state = self._read()
            result = operation(state)
            self._write(state)
            return result

    def add_account(self, profile_name: str, platform: str) -> dict[str, Any]:
        account = {
            "id": uuid.uuid4().hex,
            "profile_name": profile_name.strip(),
            "platform": platform,
            "token_expires_at": to_iso(now_utc() + timedelta(minutes=55)),
            "last_post_at": "",
            "created_at": to_iso(now_utc()),
        }

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            if any(a["profile_name"].casefold() == account["profile_name"].casefold() for a in state["accounts"]):
                raise RegistryError("Profile names must be unique")
            state["accounts"].append(account)
            return account

        return self.mutate(operation)

    def delete_account(self, account_id: str) -> None:
        def operation(state: dict[str, Any]) -> None:
            state["accounts"] = [a for a in state["accounts"] if a["id"] != account_id]
            state["jobs"] = [j for j in state["jobs"] if j["account_id"] != account_id]
        self.mutate(operation)

    def update_account(self, account_id: str, **changes: Any) -> None:
        def operation(state: dict[str, Any]) -> None:
            account = next((a for a in state["accounts"] if a["id"] == account_id), None)
            if not account:
                raise RegistryError("Account no longer exists")
            account.update(changes)
        self.mutate(operation)

    @staticmethod
    def _assert_window(state: dict[str, Any], account_id: str, planned_at: datetime) -> None:
        account = next((a for a in state["accounts"] if a["id"] == account_id), None)
        if not account:
            raise RegistryError("Choose a valid profile")
        last_post = account.get("last_post_at", "")
        if last_post and abs(planned_at - from_iso(last_post)) < POST_WINDOW:
            raise RegistryError("This profile has posted within the protected 23-hour window")
        for job in state["jobs"]:
            if job["account_id"] != account_id or job["status"] not in {"queued", "running"}:
                continue
            if abs(planned_at - from_iso(job["run_at"])) < POST_WINDOW:
                raise RegistryError("This profile already has a queued post within 23 hours")

    def add_job(self, account_id: str, video: str, caption: str, run_at: datetime, daily: bool) -> dict[str, Any]:
        job = {
            "id": uuid.uuid4().hex,
            "account_id": account_id,
            "video_path": str(Path(video).resolve()),
            "caption": caption.strip(),
            "run_at": to_iso(run_at),
            "repeat_daily": daily,
            "status": "queued",
            "publish_id": "",
            "last_error": "",
            "created_at": to_iso(now_utc()),
        }

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            self._assert_window(state, account_id, run_at.astimezone(UTC))
            state["jobs"].append(job)
            return job

        return self.mutate(operation)

    def claim_due_job(self, job_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Atomically re-check rate limits and mark one job running."""
        def operation(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
            job = next((j for j in state["jobs"] if j["id"] == job_id), None)
            if not job or job["status"] != "queued" or from_iso(job["run_at"]) > now_utc():
                raise RegistryError("Job is no longer due")
            account = next((a for a in state["accounts"] if a["id"] == job["account_id"]), None)
            if not account:
                raise RegistryError("The profile was removed")
            last_post = account.get("last_post_at", "")
            if last_post and now_utc() - from_iso(last_post) < POST_WINDOW:
                raise RegistryError("23-hour publishing guard blocked this upload")
            job["status"] = "running"
            job["last_error"] = ""
            return copy.deepcopy(job), copy.deepcopy(account)
        return self.mutate(operation)

    def complete_job(self, job_id: str, publish_id: str) -> None:
        submitted = now_utc()

        def operation(state: dict[str, Any]) -> None:
            job = next(j for j in state["jobs"] if j["id"] == job_id)
            account = next(a for a in state["accounts"] if a["id"] == job["account_id"])
            account["last_post_at"] = to_iso(submitted)
            job["publish_id"] = publish_id
            job["last_error"] = ""
            if job["repeat_daily"]:
                next_run = from_iso(job["run_at"]) + timedelta(days=1)
                while next_run - submitted < POST_WINDOW:
                    next_run += timedelta(days=1)
                job["run_at"] = to_iso(next_run)
                job["status"] = "queued"
            else:
                job["status"] = "submitted"
        self.mutate(operation)

    def fail_job(self, job_id: str, error: str) -> None:
        def operation(state: dict[str, Any]) -> None:
            job = next((j for j in state["jobs"] if j["id"] == job_id), None)
            if job:
                job.update(status="failed", last_error=error[:1000])
        self.mutate(operation)

    def delete_job(self, job_id: str) -> None:
        self.mutate(lambda state: state.update(jobs=[j for j in state["jobs"] if j["id"] != job_id]))


class SecretStore:
    def set(self, account_id: str, access: str, refresh: str) -> None:
        keyring.set_password(KEYRING_SERVICE, f"{account_id}:access", access)
        keyring.set_password(KEYRING_SERVICE, f"{account_id}:refresh", refresh)

    def get(self, account_id: str) -> tuple[str, str]:
        return (
            keyring.get_password(KEYRING_SERVICE, f"{account_id}:access") or "",
            keyring.get_password(KEYRING_SERVICE, f"{account_id}:refresh") or "",
        )

    def delete(self, account_id: str) -> None:
        for kind in ("access", "refresh"):
            try:
                keyring.delete_password(KEYRING_SERVICE, f"{account_id}:{kind}")
            except keyring.errors.PasswordDeleteError:
                pass


class ThreadSignals(QObject):
    progress = Signal(int)
    log = Signal(str)
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class BackgroundTask:
    """Runs blocking work in a real Python background thread, reporting via Qt signals."""

    def __init__(self, function: Callable[[ThreadSignals], Any]):
        self.function = function
        self.signals = ThreadSignals()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        try:
            self.signals.result.emit(self.function(self.signals))
        except Exception:
            self.signals.error.emit(traceback.format_exc())
        finally:
            self.signals.finished.emit()


class RenditionEngine:
    RESOLUTIONS = ((1080, 1920), (720, 1280), (1080, 1080), (1920, 1080))

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    @staticmethod
    def validate() -> None:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise RuntimeError("FFmpeg and FFprobe must be installed and available on PATH")

    def render(self, master: Path, output: Path, count: int, signals: ThreadSignals) -> list[str]:
        self.validate()
        if not master.is_file():
            raise FileNotFoundError(master)
        output.mkdir(parents=True, exist_ok=True)
        probe = ffmpeg.probe(str(master))
        has_audio = any(s.get("codec_type") == "audio" for s in probe.get("streams", []))
        completed: list[str] = []

        for index in range(count):
            width, height = self.RESOLUTIONS[index % len(self.RESOLUTIONS)]
            crf = 20 + (index % 4)
            sample_rate = (44100, 48000)[index % 2]
            sharpen = (0.25, 0.35, 0.45)[index % 3]
            grain = (0, 1, 2)[index % 3]
            target = output / f"{master.stem}-{index + 1:03d}-{width}x{height}-crf{crf}-{sample_rate}hz.mp4"
            signals.log.emit(f"Encoding {target.name}")

            source = ffmpeg.input(str(master))
            video = (source.video
                     .filter("scale", width, height, force_original_aspect_ratio="decrease")
                     .filter("pad", width, height, "(ow-iw)/2", "(oh-ih)/2")
                     .filter("fps", fps=30)
                     .filter("unsharp", 5, 5, sharpen, 5, 5, 0.0))
            if grain:
                video = video.filter("noise", alls=grain, allf="t")

            options = {
                "vcodec": "libx264", "preset": "medium", "crf": crf,
                "profile:v": "high", "level:v": "4.1", "pix_fmt": "yuv420p",
                "movflags": "+faststart", "map_metadata": -1,
                "metadata": "comment=SignalDesk standards-based delivery rendition",
            }
            if has_audio:
                audio = (source.audio
                         .filter("aresample", sample_rate)
                         .filter("loudnorm", I=-16, TP=-1.5, LRA=11))
                pipeline = ffmpeg.output(video, audio, str(target), acodec="aac", audio_bitrate="192k", ar=sample_rate, **options)
            else:
                pipeline = ffmpeg.output(video, str(target), **options)
            try:
                pipeline.global_args("-hide_banner", "-loglevel", "error").overwrite_output().run(
                    capture_stdout=True, capture_stderr=True
                )
            except ffmpeg.Error as exc:
                detail = exc.stderr.decode(errors="replace") if exc.stderr else str(exc)
                raise RuntimeError(f"FFmpeg failed for {target.name}: {detail}") from exc
            completed.append(str(target))
            signals.progress.emit(round((index + 1) * 100 / count))
        return completed


class TikTokPublisher:
    def __init__(self, registry: PipelineRegistry, secrets: SecretStore):
        self.registry = registry
        self.secrets = secrets

    @staticmethod
    def _json(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text[:1000]}
        if not response.ok:
            raise RuntimeError(f"TikTok API {response.status_code}: {payload}")
        error = payload.get("error", {})
        if error.get("code") not in (None, 0, "ok"):
            raise RuntimeError(f"TikTok API error: {error}")
        return payload

    def token(self, account: dict[str, Any]) -> str:
        access, refresh = self.secrets.get(account["id"])
        if not access:
            raise RuntimeError("No access token is stored for this profile")
        if from_iso(account["token_expires_at"]) > now_utc() + timedelta(minutes=5):
            return access
        client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
        client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
        if not client_key or not client_secret or not refresh:
            raise RuntimeError("Token refresh requires TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, and a refresh token")
        response = requests.post(
            f"{TIKTOK_API}/v2/oauth/token/",
            data={"client_key": client_key, "client_secret": client_secret,
                  "grant_type": "refresh_token", "refresh_token": refresh},
            headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=45,
        )
        payload = self._json(response)
        access = payload["access_token"]
        self.secrets.set(account["id"], access, payload.get("refresh_token", refresh))
        self.registry.update_account(
            account["id"],
            token_expires_at=to_iso(now_utc() + timedelta(seconds=int(payload.get("expires_in", 3600)))),
        )
        return access

    @staticmethod
    def chunk_plan(size: int) -> tuple[int, int]:
        if size <= 0:
            raise ValueError("Video is empty")
        if size <= 64 * 1024 * 1024:
            return size, 1
        chunk = 10 * 1024 * 1024
        count = max(1, size // chunk)
        if size - (count - 1) * chunk > 128 * 1024 * 1024:
            chunk = 64 * 1024 * 1024
            count = max(1, size // chunk)
        return chunk, count

    def publish(self, account: dict[str, Any], job: dict[str, Any], signals: ThreadSignals) -> str:
        video = Path(job["video_path"])
        if not video.is_file():
            raise FileNotFoundError(video)
        token = self.token(account)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
        info = self._json(requests.post(
            f"{TIKTOK_API}/v2/post/publish/creator_info/query/", headers=headers, json={}, timeout=45
        )).get("data", {})
        choices = info.get("privacy_level_options", [])
        privacy = "SELF_ONLY" if "SELF_ONLY" in choices or not choices else choices[0]
        size = video.stat().st_size
        chunk_size, chunk_count = self.chunk_plan(size)
        signals.log.emit(f"Initializing official upload for {account['profile_name']}")
        initialized = self._json(requests.post(
            f"{TIKTOK_API}/v2/post/publish/video/init/", headers=headers,
            json={
                "post_info": {
                    "title": job["caption"][:2200], "privacy_level": privacy,
                    "disable_duet": False, "disable_comment": False,
                    "disable_stitch": False, "video_cover_timestamp_ms": 1000,
                },
                "source_info": {
                    "source": "FILE_UPLOAD", "video_size": size,
                    "chunk_size": chunk_size, "total_chunk_count": chunk_count,
                },
            }, timeout=45,
        )).get("data", {})
        upload_url, publish_id = initialized.get("upload_url"), initialized.get("publish_id")
        if not upload_url or not publish_id:
            raise RuntimeError("TikTok did not return an upload URL and publish ID")

        sent = 0
        with video.open("rb") as handle:
            for index in range(chunk_count):
                amount = size - sent if index == chunk_count - 1 else min(chunk_size, size - sent)
                body = handle.read(amount)
                end = sent + len(body) - 1
                response = requests.put(
                    upload_url, data=body,
                    headers={"Content-Type": "video/mp4", "Content-Length": str(len(body)),
                             "Content-Range": f"bytes {sent}-{end}/{size}"}, timeout=180,
                )
                if not response.ok:
                    raise RuntimeError(f"Chunk upload failed ({response.status_code}): {response.text[:500]}")
                sent = end + 1
                signals.progress.emit(round(sent * 100 / size))
                signals.log.emit(f"Uploaded chunk {index + 1}/{chunk_count}")
        return publish_id


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.data_dir = Path(user_data_dir(APP_SLUG, "SignalDesk"))
        self.logger = setup_logger(self.data_dir)
        self.registry = PipelineRegistry(self.data_dir / "pipeline_registry.json")
        self.secrets = SecretStore()
        self.engine = RenditionEngine(self.logger)
        self.publisher = TikTokPublisher(self.registry, self.secrets)
        self.tasks: set[BackgroundTask] = set()
        self.running_jobs: set[str] = set()
        self.last_outputs: list[str] = []
        self.setWindowTitle(APP_NAME)
        self.resize(1240, 800)
        self.setMinimumSize(980, 680)
        self.build_ui()
        self.apply_style()
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.run_due)
        self.timer.start(30_000)
        QTimer.singleShot(2000, self.run_due)

    def build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 28)
        outer.setSpacing(20)
        header = QHBoxLayout()
        brand = QVBoxLayout()
        eyebrow = QLabel("SIGNALDESK / CONTENT OPERATIONS")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Ship clean assets. Keep the queue honest.")
        title.setObjectName("title")
        brand.addWidget(eyebrow)
        brand.addWidget(title)
        header.addLayout(brand)
        header.addStretch()
        self.status = QLabel("READY")
        self.status.setObjectName("statusPill")
        header.addWidget(self.status)
        outer.addLayout(header)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.accounts_tab(), "Profiles")
        self.tabs.addTab(self.processing_tab(), "Asset processing")
        self.tabs.addTab(self.queue_tab(), "Deployment queue")
        outer.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

    def accounts_tab(self) -> QWidget:
        page = QWidget()
        split = QSplitter(Qt.Horizontal)
        panel = QFrame(); panel.setObjectName("panel")
        left = QVBoxLayout(panel); left.setContentsMargins(24, 24, 24, 24); left.setSpacing(16)
        heading = QLabel("Connect an official channel"); heading.setObjectName("sectionTitle")
        note = QLabel("Credentials are stored in the operating system keychain, never in pipeline_registry.json.")
        note.setWordWrap(True); note.setObjectName("muted")
        left.addWidget(heading); left.addWidget(note)
        form = QFormLayout(); form.setSpacing(12)
        self.profile_name = QLineEdit(); self.profile_name.setPlaceholderText("Brand EU")
        self.platform = QComboBox(); self.platform.addItems(["TikTok"])
        self.access = QLineEdit(); self.access.setEchoMode(QLineEdit.Password); self.access.setPlaceholderText("Access token")
        self.refresh_token = QLineEdit(); self.refresh_token.setEchoMode(QLineEdit.Password); self.refresh_token.setPlaceholderText("Refresh token")
        form.addRow("Profile", self.profile_name); form.addRow("Platform", self.platform)
        form.addRow("Access token", self.access); form.addRow("Refresh token", self.refresh_token)
        left.addLayout(form)
        add = QPushButton("Add profile"); add.setObjectName("primaryButton"); add.clicked.connect(self.add_account)
        left.addWidget(add); left.addStretch()

        right = QWidget(); right_layout = QVBoxLayout(right); right_layout.setContentsMargins(24, 0, 0, 0); right_layout.setSpacing(14)
        toolbar = QHBoxLayout(); h = QLabel("Connected profiles"); h.setObjectName("sectionTitle")
        remove = QPushButton("Remove selected"); remove.setObjectName("quietButton"); remove.clicked.connect(self.delete_account)
        toolbar.addWidget(h); toolbar.addStretch(); toolbar.addWidget(remove); right_layout.addLayout(toolbar)
        self.accounts = QTableWidget(0, 5)
        self.accounts.setHorizontalHeaderLabels(["Profile", "Platform", "Token", "Last post", "Added"])
        self.configure_table(self.accounts, stretch=0); right_layout.addWidget(self.accounts)
        split.addWidget(panel); split.addWidget(right); split.setSizes([390, 770])
        layout = QVBoxLayout(page); layout.setContentsMargins(0, 18, 0, 0); layout.addWidget(split)
        return page

    def processing_tab(self) -> QWidget:
        page = QWidget(); layout = QGridLayout(page); layout.setContentsMargins(0, 18, 0, 0); layout.setHorizontalSpacing(24)
        panel = QFrame(); panel.setObjectName("panel")
        controls = QVBoxLayout(panel); controls.setContentsMargins(24, 24, 24, 24); controls.setSpacing(14)
        h = QLabel("H.264 delivery batch"); h.setObjectName("sectionTitle")
        note = QLabel("Creates standard resolution, CRF 20-23, light mobile sharpening, optional micro grain, and normalized AAC audio outputs.")
        note.setWordWrap(True); note.setObjectName("muted")
        controls.addWidget(h); controls.addWidget(note)
        self.master = QLineEdit(); self.master.setReadOnly(True); self.master.setPlaceholderText("Master media file")
        choose_master = QPushButton("Choose file"); choose_master.clicked.connect(self.choose_master)
        row = QHBoxLayout(); row.addWidget(self.master, 1); row.addWidget(choose_master); controls.addLayout(row)
        self.output = QLineEdit(); self.output.setReadOnly(True); self.output.setPlaceholderText("Output folder")
        choose_output = QPushButton("Choose folder"); choose_output.clicked.connect(self.choose_output)
        row2 = QHBoxLayout(); row2.addWidget(self.output, 1); row2.addWidget(choose_output); controls.addLayout(row2)
        self.batch = QSpinBox(); self.batch.setRange(1, 100); self.batch.setValue(50); self.batch.setSuffix(" renditions")
        controls.addWidget(self.batch)
        self.render_button = QPushButton("Start batch"); self.render_button.setObjectName("primaryButton"); self.render_button.clicked.connect(self.start_render)
        self.progress = QProgressBar(); self.progress.setValue(0)
        controls.addWidget(self.render_button); controls.addWidget(self.progress); controls.addStretch()
        log_side = QVBoxLayout(); lh = QLabel("Encoding log"); lh.setObjectName("sectionTitle")
        self.console = QPlainTextEdit(); self.console.setReadOnly(True); self.console.setMaximumBlockCount(2000)
        log_side.addWidget(lh); log_side.addWidget(self.console)
        layout.addWidget(panel, 0, 0); layout.addLayout(log_side, 0, 1); layout.setColumnStretch(0, 2); layout.setColumnStretch(1, 3)
        return page

    def queue_tab(self) -> QWidget:
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(0, 18, 0, 0); layout.setSpacing(18)
        panel = QFrame(); panel.setObjectName("panel")
        grid = QGridLayout(panel); grid.setContentsMargins(22, 18, 22, 18); grid.setSpacing(12)
        self.queue_account = QComboBox(); self.queue_video = QLineEdit(); self.queue_video.setPlaceholderText("MP4 delivery file")
        browse = QPushButton("Browse"); browse.clicked.connect(self.choose_queue_video)
        video_row = QHBoxLayout(); video_row.addWidget(self.queue_video, 1); video_row.addWidget(browse)
        self.queue_time = QDateTimeEdit(); self.queue_time.setCalendarPopup(True); self.queue_time.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.queue_time.setDateTime(datetime.now() + timedelta(minutes=10))
        self.caption = QLineEdit(); self.caption.setPlaceholderText("Caption reviewed by the channel owner")
        self.daily = QCheckBox("Repeat daily")
        add = QPushButton("Queue compliant post"); add.setObjectName("primaryButton"); add.clicked.connect(self.add_job)
        grid.addWidget(QLabel("Profile"), 0, 0); grid.addWidget(QLabel("Video"), 0, 1); grid.addWidget(QLabel("Run at"), 0, 2)
        grid.addWidget(self.queue_account, 1, 0); grid.addLayout(video_row, 1, 1); grid.addWidget(self.queue_time, 1, 2)
        grid.addWidget(QLabel("Caption"), 2, 0); grid.addWidget(self.caption, 3, 0, 1, 2); grid.addWidget(self.daily, 3, 2); grid.addWidget(add, 3, 3)
        grid.setColumnStretch(1, 2); layout.addWidget(panel)
        toolbar = QHBoxLayout(); h = QLabel("23-hour protected pipeline"); h.setObjectName("sectionTitle")
        remove = QPushButton("Remove selected"); remove.setObjectName("quietButton"); remove.clicked.connect(self.delete_job)
        run = QPushButton("Run due now"); run.clicked.connect(self.run_due)
        toolbar.addWidget(h); toolbar.addStretch(); toolbar.addWidget(remove); toolbar.addWidget(run); layout.addLayout(toolbar)
        self.jobs = QTableWidget(0, 6)
        self.jobs.setHorizontalHeaderLabels(["Profile", "Asset", "Next deployment", "Cadence", "State", "Publish ID"])
        self.configure_table(self.jobs, stretch=1); layout.addWidget(self.jobs, 1)
        return page

    @staticmethod
    def configure_table(table: QTableWidget, stretch: int) -> None:
        table.setSelectionBehavior(QTableWidget.SelectRows); table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers); table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.Stretch)
        for column in range(table.columnCount()):
            if column != stretch: table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)

    def apply_style(self) -> None:
        palette = QPalette(); palette.setColor(QPalette.Window, QColor("#11130f")); palette.setColor(QPalette.WindowText, QColor("#ebe9df"))
        palette.setColor(QPalette.Base, QColor("#171a15")); palette.setColor(QPalette.Text, QColor("#ebe9df")); palette.setColor(QPalette.Button, QColor("#24291f"))
        palette.setColor(QPalette.ButtonText, QColor("#ebe9df")); palette.setColor(QPalette.Highlight, QColor("#c7f36b")); palette.setColor(QPalette.HighlightedText, QColor("#12150f"))
        self.setPalette(palette); self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet("""
            QMainWindow,QWidget{background:#11130f;color:#ebe9df} QLabel#eyebrow{color:#c7f36b;font-size:11px;font-weight:700;letter-spacing:2px}
            QLabel#title{font-size:28px;font-weight:650;color:#f0eee5} QLabel#sectionTitle{font-size:18px;font-weight:650;color:#f0eee5}
            QLabel#muted{color:#a8ad9f} QLabel#statusPill{background:#1f2917;color:#c7f36b;border:1px solid #39472b;border-radius:15px;padding:7px 12px;font-size:10px;font-weight:700}
            QFrame#panel{background:#181b16;border:1px solid #2d3228;border-radius:12px} QTabWidget::pane{border:0}
            QTabBar::tab{background:transparent;color:#969c8d;padding:11px 18px;margin-right:4px;border-bottom:2px solid transparent}
            QTabBar::tab:hover{color:#dad9d0} QTabBar::tab:selected{color:#f0eee5;border-bottom:2px solid #c7f36b}
            QLineEdit,QSpinBox,QComboBox,QDateTimeEdit,QPlainTextEdit{background:#141712;color:#ebe9df;border:1px solid #343a2e;border-radius:7px;padding:9px 10px;selection-background-color:#c7f36b;selection-color:#12150f}
            QLineEdit:focus,QSpinBox:focus,QComboBox:focus,QDateTimeEdit:focus,QPlainTextEdit:focus{border:2px solid #98bd4f;padding:8px 9px}
            QPushButton{min-height:38px;background:#24291f;color:#e7e5dc;border:1px solid #373d31;border-radius:7px;padding:0 15px;font-weight:600}
            QPushButton:hover{background:#2c3325;border-color:#4a5340} QPushButton:disabled{color:#686d62;background:#1a1d17;border-color:#282c24}
            QPushButton#primaryButton{background:#c7f36b;color:#15180f;border-color:#c7f36b;font-weight:750} QPushButton#primaryButton:hover{background:#d4fb81;border-color:#d4fb81}
            QPushButton#quietButton{background:transparent;color:#b9bdb1} QTableWidget{background:#151813;border:1px solid #2d3228;border-radius:9px;gridline-color:#292e25;selection-background-color:#29331f;selection-color:#f0eee5}
            QHeaderView::section{background:#1d211a;color:#9fa596;border:0;border-bottom:1px solid #343a2e;padding:10px;font-size:11px;font-weight:700}
            QTableWidget::item{padding:9px} QProgressBar{background:#1b1f18;color:#dfe2d7;border:1px solid #30362b;border-radius:6px;text-align:center;min-height:20px}
            QProgressBar::chunk{background:#98bd4f;border-radius:5px} QSplitter::handle{background:transparent;width:10px}
            QCheckBox{color:#c9ccc2;spacing:8px} QCheckBox::indicator{width:17px;height:17px;border:1px solid #4a5143;border-radius:4px;background:#151813}
            QCheckBox::indicator:checked{background:#c7f36b;border-color:#c7f36b}
        """)

    def log(self, message: str) -> None:
        self.console.appendPlainText(f"{datetime.now().strftime('%H:%M:%S')}  {message}")
        self.logger.info(message)

    def error(self, title: str, detail: str) -> None:
        short = detail.strip().splitlines()[-1] if detail.strip() else "Unknown error"
        self.logger.error("%s: %s", title, detail); self.log(f"ERROR  {short}"); QMessageBox.critical(self, title, short)

    def retain_task(self, task: BackgroundTask) -> None:
        self.tasks.add(task)
        task.signals.finished.connect(lambda: self.tasks.discard(task))
        task.start()

    def selected_id(self, table: QTableWidget) -> str:
        row = table.currentRow()
        return table.item(row, 0).data(Qt.UserRole) if row >= 0 and table.item(row, 0) else ""

    def refresh(self) -> None:
        state = self.registry.snapshot(); accounts = state["accounts"]
        self.accounts.setRowCount(len(accounts)); self.queue_account.clear()
        for row, account in enumerate(accounts):
            last = from_iso(account["last_post_at"]).astimezone().strftime("%Y-%m-%d %H:%M") if account.get("last_post_at") else "Never"
            token = "Refresh soon" if from_iso(account["token_expires_at"]) <= now_utc() + timedelta(minutes=5) else "Ready"
            values = (account["profile_name"], account["platform"], token, last, from_iso(account["created_at"]).astimezone().strftime("%Y-%m-%d"))
            for col, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.UserRole, account["id"]); self.accounts.setItem(row, col, item)
            self.queue_account.addItem(account["profile_name"], account["id"])
        names = {a["id"]: a["profile_name"] for a in accounts}; jobs = sorted(state["jobs"], key=lambda j: j["run_at"])
        self.jobs.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            values = (names.get(job["account_id"], "Removed"), Path(job["video_path"]).name,
                      from_iso(job["run_at"]).astimezone().strftime("%Y-%m-%d %H:%M"),
                      "Daily" if job["repeat_daily"] else "Once", job["status"].title(), job.get("publish_id", "")[:18])
            for col, value in enumerate(values):
                item = QTableWidgetItem(value); item.setData(Qt.UserRole, job["id"]); item.setToolTip(job.get("last_error", "")); self.jobs.setItem(row, col, item)
        self.status.setText(f"{len(accounts)} PROFILES / {len(jobs)} JOBS")

    def add_account(self) -> None:
        if not all((self.profile_name.text().strip(), self.access.text().strip(), self.refresh_token.text().strip())):
            return self.error("Missing details", "Profile name, access token, and refresh token are required")
        try:
            account = self.registry.add_account(self.profile_name.text(), self.platform.currentText())
            try: self.secrets.set(account["id"], self.access.text().strip(), self.refresh_token.text().strip())
            except Exception:
                self.registry.delete_account(account["id"]); raise
            self.profile_name.clear(); self.access.clear(); self.refresh_token.clear(); self.log(f"Added {account['profile_name']}"); self.refresh()
        except Exception as exc: self.error("Could not add profile", str(exc))

    def delete_account(self) -> None:
        account_id = self.selected_id(self.accounts)
        if not account_id: return self.error("Nothing selected", "Select a profile first")
        self.registry.delete_account(account_id); self.secrets.delete(account_id); self.log("Removed profile and its queue"); self.refresh()

    def choose_master(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose master media", "", "Media (*.mp4 *.mov *.mkv *.webm)")
        if path:
            self.master.setText(path)
            if not self.output.text(): self.output.setText(str(Path(path).parent / f"{Path(path).stem}-renditions"))

    def choose_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if path: self.output.setText(path)

    def start_render(self) -> None:
        master, output = Path(self.master.text()), Path(self.output.text())
        if not master.is_file() or not self.output.text(): return self.error("Missing input", "Choose a master media file and output folder")
        self.render_button.setEnabled(False); self.progress.setValue(0)
        task = BackgroundTask(lambda signals: self.engine.render(master, output, self.batch.value(), signals))
        task.signals.log.connect(self.log); task.signals.progress.connect(self.progress.setValue)
        task.signals.error.connect(lambda detail: self.error("Encoding failed", detail))
        task.signals.result.connect(self.render_done); task.signals.finished.connect(lambda: self.render_button.setEnabled(True))
        self.retain_task(task)

    def render_done(self, result: object) -> None:
        self.last_outputs = list(result or [])
        if self.last_outputs: self.queue_video.setText(self.last_outputs[0])
        self.log(f"Completed {len(self.last_outputs)} compliant renditions")

    def choose_queue_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose delivery file", "", "MP4 (*.mp4)")
        if path: self.queue_video.setText(path)

    def add_job(self) -> None:
        local = self.queue_time.dateTime().toPython()
        if local.tzinfo is None: local = local.astimezone()
        if not self.queue_account.currentData() or not Path(self.queue_video.text()).is_file() or not self.caption.text().strip():
            return self.error("Incomplete schedule", "Choose a profile, existing MP4, and caption")
        try:
            self.registry.add_job(self.queue_account.currentData(), self.queue_video.text(), self.caption.text(), local.astimezone(UTC), self.daily.isChecked())
            self.caption.clear(); self.log("Queued post with the deterministic 23-hour guard"); self.refresh()
        except Exception as exc: self.error("Could not queue post", str(exc))

    def delete_job(self) -> None:
        job_id = self.selected_id(self.jobs)
        if not job_id: return self.error("Nothing selected", "Select a queue row first")
        if job_id in self.running_jobs: return self.error("Job is running", "Wait for the upload to finish")
        self.registry.delete_job(job_id); self.log("Removed queued post"); self.refresh()

    def run_due(self) -> None:
        for candidate in self.registry.snapshot()["jobs"]:
            if candidate["status"] != "queued" or from_iso(candidate["run_at"]) > now_utc() or candidate["id"] in self.running_jobs: continue
            try:
                job, account = self.registry.claim_due_job(candidate["id"])
            except Exception as exc:
                self.registry.fail_job(candidate["id"], str(exc)); self.log(f"Guard blocked job: {exc}"); continue
            self.running_jobs.add(job["id"])
            task = BackgroundTask(lambda signals, j=job, a=account: self.publisher.publish(a, j, signals))
            task.signals.log.connect(self.log)
            task.signals.result.connect(lambda publish_id, j=job: self.job_ok(j, str(publish_id)))
            task.signals.error.connect(lambda detail, j=job: self.job_failed(j, detail))
            task.signals.finished.connect(lambda job_id=job["id"]: self.job_finished(job_id))
            self.retain_task(task)
        self.refresh()

    def job_ok(self, job: dict[str, Any], publish_id: str) -> None:
        self.registry.complete_job(job["id"], publish_id); self.log(f"TikTok accepted publish ID {publish_id}"); self.refresh()

    def job_failed(self, job: dict[str, Any], detail: str) -> None:
        short = detail.strip().splitlines()[-1] if detail.strip() else "Unknown error"
        self.registry.fail_job(job["id"], short); self.error("Scheduled upload failed", detail); self.refresh()

    def job_finished(self, job_id: str) -> None:
        self.running_jobs.discard(job_id); self.refresh()


def main() -> int:
    app = QApplication(sys.argv); app.setApplicationName(APP_NAME); app.setOrganizationName("SignalDesk"); app.setStyle("Fusion")
    window = MainWindow(); window.show(); return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
