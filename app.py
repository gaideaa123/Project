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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse

import ffmpeg
import keyring
import requests
from platformdirs import user_data_dir
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "SignalDesk Publisher"
APP_SLUG = "signaldesk-publisher"
SERVICE_NAME = "signaldesk-publisher.tokens"
TIKTOK_API = "https://open.tiktokapis.com"
UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def configure_logging(data_dir: Path) -> logging.Logger:
    data_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(APP_SLUG)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        file_handler = logging.FileHandler(data_dir / "signaldesk.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    return logger


@dataclass(frozen=True)
class RenderProfile:
    name: str
    width: int
    height: int
    fps: int
    crf: int
    audio_rate: int = 48000


RENDER_PROFILES = (
    RenderProfile("vertical-hq", 1080, 1920, 30, 19),
    RenderProfile("vertical-web", 1080, 1920, 30, 22),
    RenderProfile("vertical-light", 720, 1280, 30, 23),
    RenderProfile("vertical-25", 1080, 1920, 25, 20),
    RenderProfile("square-hq", 1080, 1080, 30, 20),
    RenderProfile("landscape-hq", 1920, 1080, 30, 20),
)


class RegistryError(RuntimeError):
    pass


class AtomicRegistry:
    """Thread-safe JSON state with atomic replacement and a rolling backup."""

    def __init__(self, path: Path):
        self.path = path
        self.backup_path = path.with_suffix(path.suffix + ".bak")
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_unlocked({"version": 1, "accounts": [], "jobs": []})

    def _read_unlocked(self) -> dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data.get("accounts"), list) or not isinstance(data.get("jobs"), list):
                raise RegistryError("Registry schema is invalid")
            return data
        except Exception as exc:
            if self.backup_path.exists():
                with self.backup_path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)
            raise RegistryError(f"Unable to read registry: {exc}") from exc

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="registry-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            if self.path.exists():
                shutil.copy2(self.path, self.backup_path)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self._read_unlocked())

    def mutate(self, operation: Callable[[dict[str, Any]], Any]) -> Any:
        with self.lock:
            state = self._read_unlocked()
            result = operation(state)
            self._write_unlocked(state)
            return result

    def add_account(self, profile_name: str, proxy: str) -> dict[str, Any]:
        account = {
            "id": uuid.uuid4().hex,
            "profile_name": profile_name.strip(),
            "proxy": proxy.strip(),
            "token_expires_at": iso(utc_now() + timedelta(minutes=55)),
            "created_at": iso(utc_now()),
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

    def add_job(self, account_id: str, video_path: str, title: str, run_at: datetime, repeat_daily: bool) -> dict[str, Any]:
        job = {
            "id": uuid.uuid4().hex,
            "account_id": account_id,
            "video_path": str(Path(video_path).resolve()),
            "title": title.strip(),
            "run_at": iso(run_at),
            "repeat_daily": repeat_daily,
            "status": "queued",
            "publish_id": "",
            "last_error": "",
            "created_at": iso(utc_now()),
        }

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            account = next((a for a in state["accounts"] if a["id"] == account_id), None)
            if not account:
                raise RegistryError("Choose a valid account")
            for existing in state["jobs"]:
                if existing["account_id"] != account_id or existing["status"] not in {"queued", "running"}:
                    continue
                if abs((parse_iso(existing["run_at"]) - run_at.astimezone(UTC)).total_seconds()) < 23 * 3600:
                    raise RegistryError("This account already has a post queued within 23 hours")
            state["jobs"].append(job)
            return job

        return self.mutate(operation)

    def update_job(self, job_id: str, **changes: Any) -> None:
        def operation(state: dict[str, Any]) -> None:
            job = next((j for j in state["jobs"] if j["id"] == job_id), None)
            if not job:
                raise RegistryError("Job no longer exists")
            job.update(changes)

        self.mutate(operation)

    def delete_job(self, job_id: str) -> None:
        self.mutate(lambda state: state.update(jobs=[j for j in state["jobs"] if j["id"] != job_id]))


class SecretStore:
    def set_tokens(self, account_id: str, access_token: str, refresh_token: str) -> None:
        keyring.set_password(SERVICE_NAME, f"{account_id}:access", access_token)
        keyring.set_password(SERVICE_NAME, f"{account_id}:refresh", refresh_token)

    def get_tokens(self, account_id: str) -> tuple[str, str]:
        access = keyring.get_password(SERVICE_NAME, f"{account_id}:access") or ""
        refresh = keyring.get_password(SERVICE_NAME, f"{account_id}:refresh") or ""
        return access, refresh

    def delete_tokens(self, account_id: str) -> None:
        for kind in ("access", "refresh"):
            try:
                keyring.delete_password(SERVICE_NAME, f"{account_id}:{kind}")
            except keyring.errors.PasswordDeleteError:
                pass


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    log = Signal(str)
    progress = Signal(int)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, function: Callable[[WorkerSignals], Any]):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            self.signals.result.emit(self.function(self.signals))
        except Exception:
            self.signals.error.emit(traceback.format_exc())
        finally:
            self.signals.finished.emit()


class VideoRenderer:
    """Creates standards-based delivery renditions, not fingerprint-evasion mutations."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    @staticmethod
    def validate_environment() -> None:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise RuntimeError("FFmpeg and FFprobe must be installed and available on PATH")

    def render_many(self, master: Path, count: int, output_dir: Path, signals: WorkerSignals) -> list[str]:
        self.validate_environment()
        if not master.is_file():
            raise FileNotFoundError(f"Video not found: {master}")
        output_dir.mkdir(parents=True, exist_ok=True)
        probe = ffmpeg.probe(str(master))
        has_audio = any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))
        outputs: list[str] = []

        for index in range(count):
            profile = RENDER_PROFILES[index % len(RENDER_PROFILES)]
            cycle = index // len(RENDER_PROFILES)
            crf = min(28, profile.crf + cycle)
            name = f"{master.stem}-{index + 1:03d}-{profile.name}-crf{crf}.mp4"
            target = output_dir / name
            signals.log.emit(f"Rendering {name}")
            self.logger.info("Rendering %s with profile %s", target, profile.name)

            source = ffmpeg.input(str(master))
            video = (
                source.video
                .filter("scale", profile.width, profile.height, force_original_aspect_ratio="decrease")
                .filter("pad", profile.width, profile.height, "(ow-iw)/2", "(oh-ih)/2")
                .filter("fps", fps=profile.fps)
            )
            options = {
                "vcodec": "libx264",
                "preset": "medium",
                "crf": crf,
                "pix_fmt": "yuv420p",
                "movflags": "+faststart",
                "map_metadata": -1,
            }
            if has_audio:
                audio = source.audio.filter("aresample", profile.audio_rate)
                pipeline = ffmpeg.output(video, audio, str(target), acodec="aac", audio_bitrate="192k", **options)
            else:
                pipeline = ffmpeg.output(video, str(target), **options)
            try:
                pipeline.global_args("-hide_banner", "-loglevel", "error").overwrite_output().run(
                    capture_stdout=True, capture_stderr=True
                )
            except ffmpeg.Error as exc:
                detail = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
                raise RuntimeError(f"FFmpeg failed for {name}: {detail}") from exc
            outputs.append(str(target))
            signals.progress.emit(round(((index + 1) / count) * 100))
        return outputs


class TikTokClient:
    def __init__(self, registry: AtomicRegistry, secrets: SecretStore, logger: logging.Logger):
        self.registry = registry
        self.secrets = secrets
        self.logger = logger

    @staticmethod
    def _proxy_url(raw: str) -> str:
        raw = raw.strip()
        if not raw:
            return ""
        if "://" in raw:
            parsed = urlparse(raw)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or not parsed.port:
                raise ValueError("Proxy must be a valid http(s) URL")
            return raw
        parts = raw.split(":")
        if len(parts) == 2:
            host, port = parts
            return f"http://{host}:{int(port)}"
        if len(parts) == 4:
            host, port, username, password = parts
            return f"http://{quote(username)}:{quote(password)}@{host}:{int(port)}"
        raise ValueError("Proxy format must be host:port or host:port:user:pass")

    def _session(self, account: dict[str, Any]) -> requests.Session:
        session = requests.Session()
        session.headers.update({"User-Agent": f"{APP_SLUG}/1.0"})
        proxy = self._proxy_url(account.get("proxy", ""))
        if proxy:
            session.proxies.update({"http": proxy, "https": proxy})
        return session

    @staticmethod
    def _raise(response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text[:1000]}
        if not response.ok:
            raise RuntimeError(f"TikTok API {response.status_code}: {payload}")
        error = payload.get("error") or {}
        if error.get("code") not in (None, "ok", 0):
            raise RuntimeError(f"TikTok API error: {error}")
        return payload

    def access_token(self, account: dict[str, Any]) -> str:
        access, refresh = self.secrets.get_tokens(account["id"])
        if not access:
            raise RuntimeError("No access token is stored for this account")
        if parse_iso(account["token_expires_at"]) > utc_now() + timedelta(minutes=5):
            return access
        if not refresh:
            raise RuntimeError("Access token expired and no refresh token is stored")

        client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
        client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
        if not client_key or not client_secret:
            raise RuntimeError("Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET before token refresh")
        response = self._session(account).post(
            f"{TIKTOK_API}/v2/oauth/token/",
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=45,
        )
        payload = self._raise(response)
        new_access = payload["access_token"]
        new_refresh = payload.get("refresh_token", refresh)
        expires_at = utc_now() + timedelta(seconds=int(payload.get("expires_in", 3600)))
        self.secrets.set_tokens(account["id"], new_access, new_refresh)
        self.registry.update_account(account["id"], token_expires_at=iso(expires_at))
        return new_access

    def creator_info(self, account: dict[str, Any], token: str) -> dict[str, Any]:
        response = self._session(account).post(
            f"{TIKTOK_API}/v2/post/publish/creator_info/query/",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            json={},
            timeout=45,
        )
        return self._raise(response).get("data", {})

    @staticmethod
    def _chunk_plan(size: int) -> tuple[int, int]:
        if size <= 0:
            raise ValueError("Video file is empty")
        if size <= 64 * 1024 * 1024:
            return size, 1
        chunk_size = 10 * 1024 * 1024
        count = max(1, size // chunk_size)
        final_size = size - (count - 1) * chunk_size
        if final_size > 128 * 1024 * 1024:
            chunk_size = 64 * 1024 * 1024
            count = max(1, size // chunk_size)
        return chunk_size, count

    def direct_post(self, account: dict[str, Any], video: Path, title: str, signals: WorkerSignals) -> str:
        if not video.is_file():
            raise FileNotFoundError(f"Queued video no longer exists: {video}")
        token = self.access_token(account)
        info = self.creator_info(account, token)
        privacy_options = info.get("privacy_level_options", [])
        privacy = "SELF_ONLY" if "SELF_ONLY" in privacy_options or not privacy_options else privacy_options[0]
        size = video.stat().st_size
        chunk_size, chunk_count = self._chunk_plan(size)
        session = self._session(account)
        signals.log.emit(f"Initializing official TikTok upload for {account['profile_name']}")
        response = session.post(
            f"{TIKTOK_API}/v2/post/publish/video/init/",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            json={
                "post_info": {
                    "title": title[:2200],
                    "privacy_level": privacy,
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False,
                    "video_cover_timestamp_ms": 1000,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": chunk_count,
                },
            },
            timeout=45,
        )
        data = self._raise(response).get("data", {})
        upload_url = data.get("upload_url")
        publish_id = data.get("publish_id")
        if not upload_url or not publish_id:
            raise RuntimeError("TikTok did not return an upload URL and publish ID")

        sent = 0
        with video.open("rb") as handle:
            for index in range(chunk_count):
                remaining = size - sent
                amount = remaining if index == chunk_count - 1 else min(chunk_size, remaining)
                body = handle.read(amount)
                end = sent + len(body) - 1
                upload = session.put(
                    upload_url,
                    data=body,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(body)),
                        "Content-Range": f"bytes {sent}-{end}/{size}",
                    },
                    timeout=180,
                )
                if not upload.ok:
                    raise RuntimeError(f"TikTok upload failed ({upload.status_code}): {upload.text[:500]}")
                sent = end + 1
                signals.progress.emit(round((sent / size) * 100))
                signals.log.emit(f"Uploaded chunk {index + 1}/{chunk_count}")
        return publish_id


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.data_dir = Path(user_data_dir(APP_SLUG, "SignalDesk"))
        self.logger = configure_logging(self.data_dir)
        self.registry = AtomicRegistry(self.data_dir / "multi_account_registry.json")
        self.secrets = SecretStore()
        self.renderer = VideoRenderer(self.logger)
        self.tiktok = TikTokClient(self.registry, self.secrets, self.logger)
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(max(2, min(4, os.cpu_count() or 2)))
        self.render_outputs: list[str] = []
        self.running_job_ids: set[str] = set()

        self.setWindowTitle(APP_NAME)
        self.resize(1220, 790)
        self.setMinimumSize(980, 680)
        self._build_ui()
        self._apply_style()
        self.refresh_all()

        self.scheduler_timer = QTimer(self)
        self.scheduler_timer.timeout.connect(self.run_due_jobs)
        self.scheduler_timer.start(30_000)
        QTimer.singleShot(2_000, self.run_due_jobs)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(20)

        header = QHBoxLayout()
        brand = QVBoxLayout()
        eyebrow = QLabel("SIGNALDESK / PUBLISH OPERATIONS")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Content control, without the chaos.")
        title.setObjectName("title")
        brand.addWidget(eyebrow)
        brand.addWidget(title)
        header.addLayout(brand)
        header.addStretch()
        self.system_status = QLabel("SYSTEM READY")
        self.system_status.setObjectName("statusPill")
        header.addWidget(self.system_status)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._accounts_tab(), "Accounts")
        self.tabs.addTab(self._processing_tab(), "Processing")
        self.tabs.addTab(self._scheduler_tab(), "Scheduler")
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

    def _accounts_tab(self) -> QWidget:
        page = QWidget()
        split = QSplitter(Qt.Horizontal)

        form_panel = QFrame()
        form_panel.setObjectName("panel")
        form_layout = QVBoxLayout(form_panel)
        form_layout.setContentsMargins(24, 24, 24, 24)
        form_layout.setSpacing(18)
        heading = QLabel("Connect a profile")
        heading.setObjectName("sectionTitle")
        copy_label = QLabel("Tokens stay in your operating system keychain. The registry only stores references.")
        copy_label.setWordWrap(True)
        copy_label.setObjectName("muted")
        form_layout.addWidget(heading)
        form_layout.addWidget(copy_label)

        form = QFormLayout()
        form.setSpacing(12)
        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("Editorial EU")
        self.access_token = QLineEdit()
        self.access_token.setEchoMode(QLineEdit.Password)
        self.access_token.setPlaceholderText("Access token")
        self.refresh_token = QLineEdit()
        self.refresh_token.setEchoMode(QLineEdit.Password)
        self.refresh_token.setPlaceholderText("Refresh token")
        self.proxy = QLineEdit()
        self.proxy.setPlaceholderText("Optional approved gateway: host:port:user:pass")
        form.addRow("Profile name", self.profile_name)
        form.addRow("Access token", self.access_token)
        form.addRow("Refresh token", self.refresh_token)
        form.addRow("Network proxy", self.proxy)
        form_layout.addLayout(form)
        self.add_account_button = QPushButton("Add profile")
        self.add_account_button.setObjectName("primaryButton")
        self.add_account_button.clicked.connect(self.add_account)
        form_layout.addWidget(self.add_account_button)
        form_layout.addStretch()

        table_panel = QWidget()
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(24, 0, 0, 0)
        table_layout.setSpacing(14)
        top = QHBoxLayout()
        table_heading = QLabel("Connected profiles")
        table_heading.setObjectName("sectionTitle")
        top.addWidget(table_heading)
        top.addStretch()
        self.delete_account_button = QPushButton("Remove selected")
        self.delete_account_button.setObjectName("quietButton")
        self.delete_account_button.clicked.connect(self.delete_account)
        top.addWidget(self.delete_account_button)
        table_layout.addLayout(top)
        self.accounts_table = QTableWidget(0, 4)
        self.accounts_table.setHorizontalHeaderLabels(["Profile", "Token health", "Network", "Added"])
        self.accounts_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.accounts_table.setSelectionMode(QTableWidget.SingleSelection)
        self.accounts_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.accounts_table.verticalHeader().setVisible(False)
        self.accounts_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
            self.accounts_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        table_layout.addWidget(self.accounts_table)

        split.addWidget(form_panel)
        split.addWidget(table_panel)
        split.setSizes([390, 760])
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 18, 0, 0)
        page_layout.addWidget(split)
        return page

    def _processing_tab(self) -> QWidget:
        page = QWidget()
        layout = QGridLayout(page)
        layout.setContentsMargins(0, 18, 0, 0)
        layout.setHorizontalSpacing(24)
        layout.setVerticalSpacing(16)

        controls = QFrame()
        controls.setObjectName("panel")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(24, 24, 24, 24)
        controls_layout.setSpacing(16)
        heading = QLabel("Delivery renditions")
        heading.setObjectName("sectionTitle")
        details = QLabel("Standards-based H.264 outputs for publishing workflows. No fingerprint-evasion filters or deceptive mutations.")
        details.setObjectName("muted")
        details.setWordWrap(True)
        controls_layout.addWidget(heading)
        controls_layout.addWidget(details)
        self.master_video = QLineEdit()
        self.master_video.setReadOnly(True)
        self.master_video.setPlaceholderText("Choose a master MP4")
        choose = QPushButton("Choose video")
        choose.clicked.connect(self.choose_master)
        file_row = QHBoxLayout()
        file_row.addWidget(self.master_video, 1)
        file_row.addWidget(choose)
        controls_layout.addLayout(file_row)
        self.variant_count = QSpinBox()
        self.variant_count.setRange(1, 24)
        self.variant_count.setValue(3)
        self.variant_count.setSuffix(" outputs")
        controls_layout.addWidget(self.variant_count)
        self.render_button = QPushButton("Render outputs")
        self.render_button.setObjectName("primaryButton")
        self.render_button.clicked.connect(self.start_render)
        controls_layout.addWidget(self.render_button)
        self.render_progress = QProgressBar()
        self.render_progress.setValue(0)
        controls_layout.addWidget(self.render_progress)
        controls_layout.addStretch()

        console_panel = QWidget()
        console_layout = QVBoxLayout(console_panel)
        console_layout.setContentsMargins(0, 0, 0, 0)
        console_layout.setSpacing(14)
        console_heading = QLabel("Live operations log")
        console_heading.setObjectName("sectionTitle")
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(1500)
        console_layout.addWidget(console_heading)
        console_layout.addWidget(self.console)
        layout.addWidget(controls, 0, 0)
        layout.addWidget(console_panel, 0, 1)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 3)
        return page

    def _scheduler_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 18, 0, 0)
        layout.setSpacing(18)

        queue_panel = QFrame()
        queue_panel.setObjectName("panel")
        queue_layout = QGridLayout(queue_panel)
        queue_layout.setContentsMargins(22, 18, 22, 18)
        queue_layout.setHorizontalSpacing(12)
        queue_layout.setVerticalSpacing(10)
        self.schedule_account = QComboBox()
        self.schedule_video = QLineEdit()
        self.schedule_video.setPlaceholderText("Video file")
        choose = QPushButton("Browse")
        choose.clicked.connect(self.choose_schedule_video)
        self.schedule_title = QLineEdit()
        self.schedule_title.setPlaceholderText("Caption shown to the user before posting")
        self.schedule_time = QDateTimeEdit()
        self.schedule_time.setCalendarPopup(True)
        self.schedule_time.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.schedule_time.setDateTime(datetime.now() + timedelta(minutes=10))
        self.repeat_daily = QCheckBox("Repeat daily")
        add = QPushButton("Queue post")
        add.setObjectName("primaryButton")
        add.clicked.connect(self.add_job)
        queue_layout.addWidget(QLabel("Account"), 0, 0)
        queue_layout.addWidget(self.schedule_account, 1, 0)
        queue_layout.addWidget(QLabel("Video"), 0, 1)
        video_row = QHBoxLayout()
        video_row.addWidget(self.schedule_video, 1)
        video_row.addWidget(choose)
        queue_layout.addLayout(video_row, 1, 1)
        queue_layout.addWidget(QLabel("Run at"), 0, 2)
        queue_layout.addWidget(self.schedule_time, 1, 2)
        queue_layout.addWidget(QLabel("Caption"), 2, 0)
        queue_layout.addWidget(self.schedule_title, 3, 0, 1, 2)
        queue_layout.addWidget(self.repeat_daily, 3, 2)
        queue_layout.addWidget(add, 3, 3)
        queue_layout.setColumnStretch(1, 2)
        layout.addWidget(queue_panel)

        toolbar = QHBoxLayout()
        heading = QLabel("Posting pipeline")
        heading.setObjectName("sectionTitle")
        toolbar.addWidget(heading)
        toolbar.addStretch()
        remove = QPushButton("Remove selected")
        remove.setObjectName("quietButton")
        remove.clicked.connect(self.delete_job)
        toolbar.addWidget(remove)
        run = QPushButton("Run due now")
        run.clicked.connect(self.run_due_jobs)
        toolbar.addWidget(run)
        layout.addLayout(toolbar)

        self.jobs_table = QTableWidget(0, 6)
        self.jobs_table.setHorizontalHeaderLabels(["Account", "Video", "Next deployment", "Cadence", "State", "Publish ID"])
        self.jobs_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.jobs_table.setSelectionMode(QTableWidget.SingleSelection)
        self.jobs_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.jobs_table.verticalHeader().setVisible(False)
        self.jobs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.jobs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (2, 3, 4, 5):
            self.jobs_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        layout.addWidget(self.jobs_table, 1)
        return page

    def _apply_style(self) -> None:
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor("#11130f"))
        palette.setColor(QPalette.WindowText, QColor("#ebe9df"))
        palette.setColor(QPalette.Base, QColor("#171a15"))
        palette.setColor(QPalette.AlternateBase, QColor("#1d211a"))
        palette.setColor(QPalette.Text, QColor("#ebe9df"))
        palette.setColor(QPalette.Button, QColor("#24291f"))
        palette.setColor(QPalette.ButtonText, QColor("#ebe9df"))
        palette.setColor(QPalette.Highlight, QColor("#c7f36b"))
        palette.setColor(QPalette.HighlightedText, QColor("#12150f"))
        self.setPalette(palette)
        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #11130f; color: #ebe9df; }
            QLabel#eyebrow { color: #c7f36b; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
            QLabel#title { font-size: 28px; font-weight: 650; color: #f0eee5; }
            QLabel#sectionTitle { font-size: 18px; font-weight: 650; color: #f0eee5; }
            QLabel#muted { color: #a8ad9f; line-height: 1.4; }
            QLabel#statusPill { background: #1f2917; color: #c7f36b; border: 1px solid #39472b; border-radius: 15px; padding: 7px 12px; font-size: 10px; font-weight: 700; }
            QFrame#panel { background: #181b16; border: 1px solid #2d3228; border-radius: 12px; }
            QTabWidget::pane { border: 0; }
            QTabBar::tab { background: transparent; color: #969c8d; padding: 11px 18px; margin-right: 4px; border-bottom: 2px solid transparent; }
            QTabBar::tab:hover { color: #dad9d0; }
            QTabBar::tab:selected { color: #f0eee5; border-bottom: 2px solid #c7f36b; }
            QLineEdit, QSpinBox, QComboBox, QDateTimeEdit, QPlainTextEdit { background: #141712; color: #ebe9df; border: 1px solid #343a2e; border-radius: 7px; padding: 9px 10px; selection-background-color: #c7f36b; selection-color: #12150f; }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QDateTimeEdit:focus, QPlainTextEdit:focus { border: 2px solid #98bd4f; padding: 8px 9px; }
            QLineEdit:read-only { color: #a8ad9f; background: #151813; }
            QPushButton { min-height: 38px; background: #24291f; color: #e7e5dc; border: 1px solid #373d31; border-radius: 7px; padding: 0 15px; font-weight: 600; }
            QPushButton:hover { background: #2c3325; border-color: #4a5340; }
            QPushButton:pressed { background: #1d2119; }
            QPushButton:disabled { color: #686d62; background: #1a1d17; border-color: #282c24; }
            QPushButton#primaryButton { background: #c7f36b; color: #15180f; border: 1px solid #c7f36b; font-weight: 750; }
            QPushButton#primaryButton:hover { background: #d4fb81; border-color: #d4fb81; }
            QPushButton#quietButton { background: transparent; color: #b9bdb1; }
            QTableWidget { background: #151813; alternate-background-color: #191d17; border: 1px solid #2d3228; border-radius: 9px; gridline-color: #292e25; selection-background-color: #29331f; selection-color: #f0eee5; }
            QHeaderView::section { background: #1d211a; color: #9fa596; border: 0; border-bottom: 1px solid #343a2e; padding: 10px; font-size: 11px; font-weight: 700; }
            QTableWidget::item { padding: 9px; }
            QProgressBar { background: #1b1f18; color: #dfe2d7; border: 1px solid #30362b; border-radius: 6px; text-align: center; min-height: 20px; }
            QProgressBar::chunk { background: #98bd4f; border-radius: 5px; }
            QSplitter::handle { background: transparent; width: 10px; }
            QCheckBox { color: #c9ccc2; spacing: 8px; }
            QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #4a5143; border-radius: 4px; background: #151813; }
            QCheckBox::indicator:checked { background: #c7f36b; border-color: #c7f36b; }
            QScrollBar:vertical { width: 10px; background: #141712; }
            QScrollBar::handle:vertical { background: #3a4034; border-radius: 5px; min-height: 28px; }
        """)

    def log(self, message: str) -> None:
        self.console.appendPlainText(f"{datetime.now().strftime('%H:%M:%S')}  {message}")
        self.logger.info(message)

    def show_error(self, title: str, detail: str) -> None:
        self.logger.error("%s: %s", title, detail)
        short = detail.strip().splitlines()[-1] if detail.strip() else "Unknown error"
        self.log(f"ERROR  {short}")
        QMessageBox.critical(self, title, short)

    def refresh_all(self) -> None:
        state = self.registry.snapshot()
        accounts = state["accounts"]
        self.accounts_table.setRowCount(len(accounts))
        self.schedule_account.clear()
        for row, account in enumerate(accounts):
            expires = parse_iso(account["token_expires_at"])
            health = "Refresh soon" if expires <= utc_now() + timedelta(minutes=5) else "Ready"
            network = "Approved proxy" if account.get("proxy") else "Direct"
            created = parse_iso(account["created_at"]).astimezone().strftime("%Y-%m-%d")
            for column, value in enumerate((account["profile_name"], health, network, created)):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, account["id"])
                self.accounts_table.setItem(row, column, item)
            self.schedule_account.addItem(account["profile_name"], account["id"])

        account_names = {a["id"]: a["profile_name"] for a in accounts}
        jobs = sorted(state["jobs"], key=lambda job: job["run_at"])
        self.jobs_table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            values = (
                account_names.get(job["account_id"], "Removed account"),
                Path(job["video_path"]).name,
                parse_iso(job["run_at"]).astimezone().strftime("%Y-%m-%d %H:%M"),
                "Daily" if job["repeat_daily"] else "Once",
                job["status"].title(),
                job.get("publish_id", "")[:18],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, job["id"])
                if job.get("last_error"):
                    item.setToolTip(job["last_error"])
                self.jobs_table.setItem(row, column, item)
        self.system_status.setText(f"{len(accounts)} ACCOUNTS / {len(jobs)} JOBS")

    def add_account(self) -> None:
        name = self.profile_name.text().strip()
        access = self.access_token.text().strip()
        refresh = self.refresh_token.text().strip()
        if not name or not access or not refresh:
            self.show_error("Missing details", "Profile name, access token, and refresh token are required")
            return
        try:
            if self.proxy.text().strip():
                TikTokClient._proxy_url(self.proxy.text())
            account = self.registry.add_account(name, self.proxy.text())
            try:
                self.secrets.set_tokens(account["id"], access, refresh)
            except Exception:
                self.registry.delete_account(account["id"])
                raise
            self.profile_name.clear()
            self.access_token.clear()
            self.refresh_token.clear()
            self.proxy.clear()
            self.log(f"Added profile {name}; secrets stored in the OS keychain")
            self.refresh_all()
        except Exception as exc:
            self.show_error("Could not add profile", str(exc))

    def selected_id(self, table: QTableWidget) -> str:
        row = table.currentRow()
        if row < 0 or not table.item(row, 0):
            return ""
        return table.item(row, 0).data(Qt.UserRole) or ""

    def delete_account(self) -> None:
        account_id = self.selected_id(self.accounts_table)
        if not account_id:
            self.show_error("Nothing selected", "Select an account first")
            return
        self.registry.delete_account(account_id)
        self.secrets.delete_tokens(account_id)
        self.log("Removed account and its queued jobs")
        self.refresh_all()

    def choose_master(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose master video", "", "Video files (*.mp4 *.mov *.mkv *.webm)")
        if path:
            self.master_video.setText(path)

    def start_render(self) -> None:
        master = Path(self.master_video.text())
        if not master.is_file():
            self.show_error("Choose a video", "Select an existing master video")
            return
        output_dir = master.parent / f"{master.stem}-renditions"
        count = self.variant_count.value()
        self.render_button.setEnabled(False)
        self.render_progress.setValue(0)
        worker = Worker(lambda signals: self.renderer.render_many(master, count, output_dir, signals))
        worker.signals.log.connect(self.log)
        worker.signals.progress.connect(self.render_progress.setValue)
        worker.signals.error.connect(lambda detail: self.show_error("Rendering failed", detail))
        worker.signals.result.connect(self._render_complete)
        worker.signals.finished.connect(lambda: self.render_button.setEnabled(True))
        self.pool.start(worker)

    def _render_complete(self, outputs: object) -> None:
        self.render_outputs = list(outputs or [])
        if self.render_outputs:
            self.schedule_video.setText(self.render_outputs[0])
        self.log(f"Finished {len(self.render_outputs)} delivery renditions")

    def choose_schedule_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose video to schedule", "", "MP4 video (*.mp4)")
        if path:
            self.schedule_video.setText(path)

    def add_job(self) -> None:
        account_id = self.schedule_account.currentData()
        video = self.schedule_video.text().strip()
        title = self.schedule_title.text().strip()
        local_dt = self.schedule_time.dateTime().toPython()
        if local_dt.tzinfo is None:
            local_dt = local_dt.astimezone()
        if not account_id or not Path(video).is_file() or not title:
            self.show_error("Incomplete schedule", "Choose an account, an existing MP4, and a caption")
            return
        try:
            self.registry.add_job(account_id, video, title, local_dt.astimezone(UTC), self.repeat_daily.isChecked())
            self.log("Queued post through the official Content Posting API")
            self.schedule_title.clear()
            self.refresh_all()
        except Exception as exc:
            self.show_error("Could not queue post", str(exc))

    def delete_job(self) -> None:
        job_id = self.selected_id(self.jobs_table)
        if not job_id:
            self.show_error("Nothing selected", "Select a scheduler row first")
            return
        if job_id in self.running_job_ids:
            self.show_error("Job is running", "Wait for the active upload to finish")
            return
        self.registry.delete_job(job_id)
        self.log("Removed scheduled job")
        self.refresh_all()

    def run_due_jobs(self) -> None:
        state = self.registry.snapshot()
        accounts = {a["id"]: a for a in state["accounts"]}
        due = [
            job for job in state["jobs"]
            if job["status"] == "queued" and parse_iso(job["run_at"]) <= utc_now() and job["id"] not in self.running_job_ids
        ]
        for job in due:
            account = accounts.get(job["account_id"])
            if not account:
                self.registry.update_job(job["id"], status="failed", last_error="Account was removed")
                continue
            self.running_job_ids.add(job["id"])
            self.registry.update_job(job["id"], status="running", last_error="")
            worker = Worker(lambda signals, j=job, a=account: self.tiktok.direct_post(a, Path(j["video_path"]), j["title"], signals))
            worker.signals.log.connect(self.log)
            worker.signals.progress.connect(lambda value, job_id=job["id"]: self.log(f"Upload {job_id[:6]}: {value}%"))
            worker.signals.result.connect(lambda publish_id, j=job: self._job_succeeded(j, str(publish_id)))
            worker.signals.error.connect(lambda detail, j=job: self._job_failed(j, detail))
            worker.signals.finished.connect(lambda job_id=job["id"]: self._job_finished(job_id))
            self.pool.start(worker)
        if due:
            self.refresh_all()

    def _job_succeeded(self, job: dict[str, Any], publish_id: str) -> None:
        if job["repeat_daily"]:
            next_run = parse_iso(job["run_at"]) + timedelta(days=1)
            while next_run <= utc_now():
                next_run += timedelta(days=1)
            self.registry.update_job(job["id"], status="queued", publish_id=publish_id, run_at=iso(next_run), last_error="")
            self.log(f"Submitted post {publish_id}; next daily run is queued")
        else:
            self.registry.update_job(job["id"], status="submitted", publish_id=publish_id, last_error="")
            self.log(f"Submitted post {publish_id} to TikTok")
        self.refresh_all()

    def _job_failed(self, job: dict[str, Any], detail: str) -> None:
        short = detail.strip().splitlines()[-1] if detail.strip() else "Unknown upload error"
        self.registry.update_job(job["id"], status="failed", last_error=short)
        self.show_error("Scheduled upload failed", detail)
        self.refresh_all()

    def _job_finished(self, job_id: str) -> None:
        self.running_job_ids.discard(job_id)
        self.refresh_all()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("SignalDesk")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
