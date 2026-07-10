from __future__ import annotations

import copy
import json
import logging
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
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateTimeEdit, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSpinBox, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

APP_NAME = "SignalDesk Agency Console"
APP_ID = "signaldesk-agency-console"
KEYRING_SERVICE = "signaldesk-agency-console.oauth"
API_ROOT = "https://open.tiktokapis.com"
UTC = timezone.utc
WINDOW = timedelta(hours=23)


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def setup_logger(data_dir: Path) -> logging.Logger:
    data_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(APP_ID)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = logging.FileHandler(data_dir / "signaldesk.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


class RegistryError(RuntimeError):
    pass


class RateLimitError(RegistryError):
    pass


class PipelineRegistry:
    """Atomic, thread-safe state and deterministic 23-hour posting guard."""

    EMPTY = {"schema": 2, "accounts": [], "jobs": [], "deliveries": []}

    def __init__(self, path: Path):
        self.path = path
        self.backup = path.with_suffix(path.suffix + ".bak")
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_unlocked(copy.deepcopy(self.EMPTY))

    def _read_unlocked(self) -> dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                state = json.load(handle)
        except Exception as primary:
            if not self.backup.exists():
                raise RegistryError(f"Registry could not be read: {primary}") from primary
            with self.backup.open("r", encoding="utf-8") as handle:
                state = json.load(handle)
        for key in ("accounts", "jobs", "deliveries"):
            state.setdefault(key, [])
            if not isinstance(state[key], list):
                raise RegistryError(f"Registry field '{key}' is invalid")
        state["schema"] = 2
        return state

    def _write_unlocked(self, state: dict[str, Any]) -> None:
        descriptor, temporary = tempfile.mkstemp(
            prefix="pipeline-", suffix=".json", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            if self.path.exists():
                shutil.copy2(self.path, self.backup)
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

    @staticmethod
    def _account(state: dict[str, Any], account_id: str) -> dict[str, Any]:
        account = next((item for item in state["accounts"] if item["id"] == account_id), None)
        if not account:
            raise RegistryError("The selected profile no longer exists")
        return account

    @staticmethod
    def _assert_window(
        state: dict[str, Any], account_id: str, candidate: datetime,
        ignored_job_id: str | None = None, include_running: bool = True,
    ) -> None:
        candidate = candidate.astimezone(UTC)
        for delivery in state["deliveries"]:
            if delivery["account_id"] != account_id:
                continue
            posted_at = from_iso(delivery["posted_at"])
            if abs(candidate - posted_at) < WINDOW:
                allowed = posted_at + WINDOW
                raise RateLimitError(
                    f"23-hour guard: this profile cannot post before "
                    f"{allowed.astimezone().strftime('%Y-%m-%d %H:%M %Z')}"
                )
        active_states = {"queued", "running"} if include_running else {"queued"}
        for job in state["jobs"]:
            if job["id"] == ignored_job_id or job["account_id"] != account_id:
                continue
            if job["status"] not in active_states:
                continue
            existing = from_iso(job["run_at"])
            if abs(candidate - existing) < WINDOW:
                raise RateLimitError(
                    "23-hour guard: another queued deployment for this profile is too close"
                )

    def add_account(self, name: str, platform: str, proxy: str) -> dict[str, Any]:
        account = {
            "id": uuid.uuid4().hex,
            "name": name.strip(),
            "platform": platform.strip(),
            "proxy": proxy.strip(),
            "token_expires_at": to_iso(now_utc() + timedelta(minutes=55)),
            "created_at": to_iso(now_utc()),
        }

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            if any(item["name"].casefold() == account["name"].casefold() for item in state["accounts"]):
                raise RegistryError("Profile names must be unique")
            state["accounts"].append(account)
            return account

        return self.mutate(operation)

    def remove_account(self, account_id: str) -> None:
        def operation(state: dict[str, Any]) -> None:
            state["accounts"] = [item for item in state["accounts"] if item["id"] != account_id]
            state["jobs"] = [item for item in state["jobs"] if item["account_id"] != account_id]
        self.mutate(operation)

    def update_account(self, account_id: str, **changes: Any) -> None:
        def operation(state: dict[str, Any]) -> None:
            self._account(state, account_id).update(changes)
        self.mutate(operation)

    def queue_job(
        self, account_id: str, video: Path, caption: str,
        run_at: datetime, repeat_daily: bool,
    ) -> dict[str, Any]:
        run_at = run_at.astimezone(UTC)
        job = {
            "id": uuid.uuid4().hex,
            "account_id": account_id,
            "video": str(video.resolve()),
            "caption": caption.strip(),
            "run_at": to_iso(run_at),
            "repeat_daily": repeat_daily,
            "status": "queued",
            "publish_id": "",
            "last_error": "",
            "created_at": to_iso(now_utc()),
        }

        def operation(state: dict[str, Any]) -> dict[str, Any]:
            self._account(state, account_id)
            self._assert_window(state, account_id, run_at)
            state["jobs"].append(job)
            return job
        return self.mutate(operation)

    def remove_job(self, job_id: str) -> None:
        def operation(state: dict[str, Any]) -> None:
            state["jobs"] = [item for item in state["jobs"] if item["id"] != job_id]
        self.mutate(operation)

    def claim_due_job(self, job_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Atomically re-check history and claim a job before any network request."""
        def operation(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
            job = next((item for item in state["jobs"] if item["id"] == job_id), None)
            if not job or job["status"] != "queued":
                raise RegistryError("Deployment is no longer available")
            account = self._account(state, job["account_id"])
            self._assert_window(
                state, job["account_id"], now_utc(),
                ignored_job_id=job_id, include_running=True,
            )
            job["status"] = "running"
            job["last_error"] = ""
            job["claimed_at"] = to_iso(now_utc())
            return copy.deepcopy(job), copy.deepcopy(account)
        return self.mutate(operation)

    def fail_job(self, job_id: str, error: str) -> None:
        def operation(state: dict[str, Any]) -> None:
            job = next((item for item in state["jobs"] if item["id"] == job_id), None)
            if job:
                job.update(status="failed", last_error=error[:1500])
        self.mutate(operation)

    def complete_job(self, job_id: str, publish_id: str) -> None:
        submitted_at = now_utc()

        def operation(state: dict[str, Any]) -> None:
            job = next((item for item in state["jobs"] if item["id"] == job_id), None)
            if not job:
                raise RegistryError("Completed deployment is missing from the registry")
            state["deliveries"].append({
                "id": uuid.uuid4().hex,
                "job_id": job_id,
                "account_id": job["account_id"],
                "publish_id": publish_id,
                "posted_at": to_iso(submitted_at),
            })
            job.update(publish_id=publish_id, last_error="")
            if job["repeat_daily"]:
                next_run = from_iso(job["run_at"]) + timedelta(days=1)
                while next_run < submitted_at + WINDOW:
                    next_run += timedelta(days=1)
                job.update(status="queued", run_at=to_iso(next_run))
            else:
                job["status"] = "submitted"
        self.mutate(operation)


class SecretVault:
    def save(self, account_id: str, access: str, refresh: str) -> None:
        keyring.set_password(KEYRING_SERVICE, f"{account_id}:access", access)
        keyring.set_password(KEYRING_SERVICE, f"{account_id}:refresh", refresh)

    def load(self, account_id: str) -> tuple[str, str]:
        return (
            keyring.get_password(KEYRING_SERVICE, f"{account_id}:access") or "",
            keyring.get_password(KEYRING_SERVICE, f"{account_id}:refresh") or "",
        )

    def remove(self, account_id: str) -> None:
        for suffix in ("access", "refresh"):
            try:
                keyring.delete_password(KEYRING_SERVICE, f"{account_id}:{suffix}")
            except keyring.errors.PasswordDeleteError:
                pass


class BackgroundSignals(QObject):
    log = Signal(str)
    progress = Signal(int)
    result = Signal(object)
    error = Signal(str)
    finished = Signal()


class ThreadRunner:
    """Runs blocking work in daemon threads and reports safely through Qt signals."""

    def __init__(self):
        self._threads: set[threading.Thread] = set()
        self._lock = threading.Lock()

    def start(self, function: Callable[[BackgroundSignals], Any]) -> BackgroundSignals:
        signals = BackgroundSignals()

        def target() -> None:
            try:
                signals.result.emit(function(signals))
            except Exception:
                signals.error.emit(traceback.format_exc())
            finally:
                signals.finished.emit()
                with self._lock:
                    self._threads.discard(threading.current_thread())

        thread = threading.Thread(target=target, daemon=True, name=f"signaldesk-{uuid.uuid4().hex[:6]}")
        with self._lock:
            self._threads.add(thread)
        thread.start()
        return signals


@dataclass(frozen=True)
class Rendition:
    width: int
    height: int
    fps: int
    crf: int
    audio_rate: int
    sharpen: float
    grain: int


class H264BatchEncoder:
    RESOLUTIONS = ((1080, 1920), (720, 1280), (1080, 1080), (1920, 1080))

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    @staticmethod
    def check_tools() -> None:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise RuntimeError("FFmpeg and FFprobe are required on PATH")

    @classmethod
    def plan(cls, index: int) -> Rendition:
        width, height = cls.RESOLUTIONS[index % len(cls.RESOLUTIONS)]
        crf = 20 + (index % 4)
        audio_rate = 44100 if index % 2 == 0 else 48000
        sharpen = (0.18, 0.24, 0.30)[index % 3]
        grain = (0, 1, 2)[index % 3]
        return Rendition(width, height, 30, crf, audio_rate, sharpen, grain)

    def encode(
        self, source: Path, output_dir: Path, count: int,
        signals: BackgroundSignals,
    ) -> list[str]:
        self.check_tools()
        if not source.is_file():
            raise FileNotFoundError(f"Master media not found: {source}")
        output_dir.mkdir(parents=True, exist_ok=True)
        probe = ffmpeg.probe(str(source))
        has_video = any(stream.get("codec_type") == "video" for stream in probe.get("streams", []))
        has_audio = any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))
        if not has_video:
            raise RuntimeError("The selected asset contains no video stream")

        outputs: list[str] = []
        for index in range(count):
            profile = self.plan(index)
            filename = (
                f"{source.stem}-{index + 1:03d}-"
                f"{profile.width}x{profile.height}-crf{profile.crf}-"
                f"{profile.audio_rate // 1000}k.mp4"
            )
            target = output_dir / filename
            signals.log.emit(
                f"Encoding {filename}: CRF {profile.crf}, "
                f"{profile.audio_rate} Hz, grain {profile.grain}"
            )
            input_stream = ffmpeg.input(str(source))
            video = (
                input_stream.video
                .filter("scale", profile.width, profile.height, force_original_aspect_ratio="decrease")
                .filter("pad", profile.width, profile.height, "(ow-iw)/2", "(oh-ih)/2", color="black")
                .filter("fps", fps=profile.fps)
                .filter("unsharp", 5, 5, profile.sharpen, 5, 5, 0.0)
            )
            if profile.grain:
                video = video.filter("noise", alls=profile.grain, allf="t")

            common = {
                "vcodec": "libx264",
                "preset": "medium",
                "profile:v": "high",
                "level:v": "4.1",
                "crf": profile.crf,
                "pix_fmt": "yuv420p",
                "movflags": "+faststart",
                "map_metadata": -1,
                "metadata": "encoder=SignalDesk",
            }
            if has_audio:
                audio = (
                    input_stream.audio
                    .filter("aresample", profile.audio_rate)
                    .filter("loudnorm", I=-16, LRA=11, TP=-1.5)
                )
                pipeline = ffmpeg.output(
                    video, audio, str(target), acodec="aac",
                    audio_bitrate="192k", ar=profile.audio_rate, **common,
                )
            else:
                pipeline = ffmpeg.output(video, str(target), **common)
            try:
                pipeline.global_args("-hide_banner", "-loglevel", "error").overwrite_output().run(
                    capture_stdout=True, capture_stderr=True
                )
            except ffmpeg.Error as exc:
                stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else str(exc)
                raise RuntimeError(f"FFmpeg failed for {filename}: {stderr}") from exc
            outputs.append(str(target))
            signals.progress.emit(round((index + 1) * 100 / count))
        return outputs


class TikTokPostingClient:
    def __init__(self, registry: PipelineRegistry, vault: SecretVault):
        self.registry = registry
        self.vault = vault

    @staticmethod
    def normalize_proxy(raw: str) -> str:
        raw = raw.strip()
        if not raw:
            return ""
        if "://" in raw:
            parsed = urlparse(raw)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or not parsed.port:
                raise ValueError("Proxy must be a valid HTTP(S) URL")
            return raw
        parts = raw.split(":")
        if len(parts) == 2:
            host, port = parts
            return f"http://{host}:{int(port)}"
        if len(parts) == 4:
            host, port, username, password = parts
            return f"http://{quote(username)}:{quote(password)}@{host}:{int(port)}"
        raise ValueError("Proxy must be host:port or host:port:user:pass")

    def session(self, account: dict[str, Any]) -> requests.Session:
        session = requests.Session()
        session.headers["User-Agent"] = f"{APP_ID}/2.0"
        proxy = self.normalize_proxy(account.get("proxy", ""))
        if proxy:
            session.proxies.update({"http": proxy, "https": proxy})
        return session

    @staticmethod
    def payload(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            data = {"body": response.text[:1000]}
        if not response.ok:
            raise RuntimeError(f"TikTok API {response.status_code}: {data}")
        error = data.get("error") or {}
        if error.get("code") not in (None, 0, "ok"):
            raise RuntimeError(f"TikTok API error: {error}")
        return data

    def token(self, account: dict[str, Any]) -> str:
        access, refresh = self.vault.load(account["id"])
        if not access:
            raise RuntimeError("No access token is stored for this profile")
        if from_iso(account["token_expires_at"]) > now_utc() + timedelta(minutes=5):
            return access
        if not refresh:
            raise RuntimeError("The access token expired and no refresh token is stored")
        client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
        client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
        if not client_key or not client_secret:
            raise RuntimeError("Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET for refresh")
        response = self.session(account).post(
            f"{API_ROOT}/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
            timeout=45,
        )
        data = self.payload(response)
        new_access = data["access_token"]
        new_refresh = data.get("refresh_token", refresh)
        expires = now_utc() + timedelta(seconds=int(data.get("expires_in", 3600)))
        self.vault.save(account["id"], new_access, new_refresh)
        self.registry.update_account(account["id"], token_expires_at=to_iso(expires))
        return new_access

    @staticmethod
    def chunk_plan(size: int) -> tuple[int, int]:
        if size <= 0:
            raise ValueError("Video is empty")
        mib = 1024 * 1024
        if size <= 64 * mib:
            return size, 1
        chunk_size = 10 * mib
        count = max(1, size // chunk_size)
        final_size = size - chunk_size * (count - 1)
        if final_size > 128 * mib:
            chunk_size = 64 * mib
            count = max(1, size // chunk_size)
        return chunk_size, count

    def creator_info(self, session: requests.Session, token: str) -> dict[str, Any]:
        response = session.post(
            f"{API_ROOT}/v2/post/publish/creator_info/query/",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            json={}, timeout=45,
        )
        return self.payload(response).get("data", {})

    def publish(
        self, account: dict[str, Any], video: Path,
        caption: str, signals: BackgroundSignals,
    ) -> str:
        if account.get("platform") != "TikTok":
            raise RuntimeError("This build currently implements TikTok's official posting API only")
        if not video.is_file() or video.suffix.lower() != ".mp4":
            raise FileNotFoundError("The queued MP4 file is missing")
        token = self.token(account)
        session = self.session(account)
        creator = self.creator_info(session, token)
        options = creator.get("privacy_level_options") or []
        privacy = "SELF_ONLY" if "SELF_ONLY" in options or not options else options[0]
        size = video.stat().st_size
        chunk_size, chunk_count = self.chunk_plan(size)
        signals.log.emit(f"Initializing official upload for {account['name']}")
        response = session.post(
            f"{API_ROOT}/v2/post/publish/video/init/",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            json={
                "post_info": {
                    "title": caption[:2200],
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
        data = self.payload(response).get("data", {})
        upload_url, publish_id = data.get("upload_url"), data.get("publish_id")
        if not upload_url or not publish_id:
            raise RuntimeError("TikTok returned no upload URL or publish ID")

        sent = 0
        with video.open("rb") as handle:
            for index in range(chunk_count):
                amount = size - sent if index == chunk_count - 1 else min(chunk_size, size - sent)
                body = handle.read(amount)
                if not body:
                    raise RuntimeError("Unexpected end of video during upload")
                end = sent + len(body) - 1
                uploaded = session.put(
                    upload_url, data=body,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(body)),
                        "Content-Range": f"bytes {sent}-{end}/{size}",
                    },
                    timeout=240,
                )
                if not uploaded.ok:
                    raise RuntimeError(f"TikTok upload {uploaded.status_code}: {uploaded.text[:600]}")
                sent = end + 1
                signals.progress.emit(round(sent * 100 / size))
                signals.log.emit(f"Uploaded chunk {index + 1}/{chunk_count}")
        return publish_id


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.data_dir = Path(user_data_dir(APP_ID, "SignalDesk"))
        self.logger = setup_logger(self.data_dir)
        self.registry = PipelineRegistry(self.data_dir / "pipeline_registry.json")
        self.vault = SecretVault()
        self.encoder = H264BatchEncoder(self.logger)
        self.client = TikTokPostingClient(self.registry, self.vault)
        self.runner = ThreadRunner()
        self.active_jobs: set[str] = set()
        self.last_outputs: list[str] = []
        self.setWindowTitle(APP_NAME)
        self.resize(1240, 800)
        self.setMinimumSize(1020, 690)
        self.build_ui()
        self.apply_theme()
        self.refresh()
        self.scheduler = QTimer(self)
        self.scheduler.timeout.connect(self.run_due_jobs)
        self.scheduler.start(30_000)
        QTimer.singleShot(1500, self.run_due_jobs)

    def build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 28)
        outer.setSpacing(20)
        header = QHBoxLayout()
        brand = QVBoxLayout()
        eyebrow = QLabel("SIGNALDESK / AGENCY OPERATIONS")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Ship content with a paper trail.")
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
        self.tabs.addTab(self.accounts_tab(), "Profile Manager")
        self.tabs.addTab(self.processing_tab(), "Batch Processing")
        self.tabs.addTab(self.queue_tab(), "Deployment Queue")
        outer.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

    def accounts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 18, 0, 0)
        split = QSplitter(Qt.Horizontal)
        form_panel = QFrame()
        form_panel.setObjectName("panel")
        form_layout = QVBoxLayout(form_panel)
        form_layout.setContentsMargins(24, 24, 24, 24)
        form_layout.setSpacing(16)
        heading = QLabel("Connect an official channel")
        heading.setObjectName("sectionTitle")
        note = QLabel("OAuth tokens stay in the operating system keychain. JSON never contains credentials.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        form_layout.addWidget(heading)
        form_layout.addWidget(note)
        form = QFormLayout()
        form.setSpacing(12)
        self.account_name = QLineEdit()
        self.account_name.setPlaceholderText("Brand Europe")
        self.platform = QComboBox()
        self.platform.addItem("TikTok")
        self.access_token = QLineEdit()
        self.access_token.setEchoMode(QLineEdit.Password)
        self.access_token.setPlaceholderText("Official OAuth access token")
        self.refresh_token = QLineEdit()
        self.refresh_token.setEchoMode(QLineEdit.Password)
        self.refresh_token.setPlaceholderText("Official OAuth refresh token")
        self.proxy = QLineEdit()
        self.proxy.setPlaceholderText("Optional approved corporate gateway")
        form.addRow("Profile", self.account_name)
        form.addRow("Platform", self.platform)
        form.addRow("Access token", self.access_token)
        form.addRow("Refresh token", self.refresh_token)
        form.addRow("Network gateway", self.proxy)
        form_layout.addLayout(form)
        add = QPushButton("Add profile")
        add.setObjectName("primaryButton")
        add.clicked.connect(self.add_account)
        form_layout.addWidget(add)
        form_layout.addStretch()

        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(24, 0, 0, 0)
        toolbar = QHBoxLayout()
        list_title = QLabel("Authorized profiles")
        list_title.setObjectName("sectionTitle")
        toolbar.addWidget(list_title)
        toolbar.addStretch()
        remove = QPushButton("Remove selected")
        remove.setObjectName("quietButton")
        remove.clicked.connect(self.remove_account)
        toolbar.addWidget(remove)
        list_layout.addLayout(toolbar)
        self.accounts = QTableWidget(0, 5)
        self.accounts.setHorizontalHeaderLabels(["Profile", "Platform", "Token", "Network", "Added"])
        self.configure_table(self.accounts, stretch_column=0)
        list_layout.addWidget(self.accounts)
        split.addWidget(form_panel)
        split.addWidget(list_panel)
        split.setSizes([400, 760])
        layout.addWidget(split)
        return page

    def processing_tab(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 18, 0, 0)
        grid.setHorizontalSpacing(24)
        controls = QFrame()
        controls.setObjectName("panel")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(24, 24, 24, 24)
        controls_layout.setSpacing(14)
        heading = QLabel("H.264 rendition batch")
        heading.setObjectName("sectionTitle")
        note = QLabel("CRF 20 to 23, normalized H.264/AAC, mobile sharpening, optional micro-grain, and loudness normalization.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        controls_layout.addWidget(heading)
        controls_layout.addWidget(note)
        self.master = QLineEdit()
        self.master.setReadOnly(True)
        self.master.setPlaceholderText("Master media file")
        master_button = QPushButton("Select master")
        master_button.clicked.connect(self.choose_master)
        master_row = QHBoxLayout()
        master_row.addWidget(self.master, 1)
        master_row.addWidget(master_button)
        controls_layout.addLayout(master_row)
        self.output_dir = QLineEdit()
        self.output_dir.setReadOnly(True)
        self.output_dir.setPlaceholderText("Output folder")
        output_button = QPushButton("Select folder")
        output_button.clicked.connect(self.choose_output)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_dir, 1)
        output_row.addWidget(output_button)
        controls_layout.addLayout(output_row)
        self.batch_size = QSpinBox()
        self.batch_size.setRange(1, 100)
        self.batch_size.setValue(50)
        self.batch_size.setSuffix(" renditions")
        controls_layout.addWidget(self.batch_size)
        self.render_button = QPushButton("Start batch")
        self.render_button.setObjectName("primaryButton")
        self.render_button.clicked.connect(self.start_batch)
        controls_layout.addWidget(self.render_button)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        controls_layout.addWidget(self.progress)
        controls_layout.addStretch()

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_title = QLabel("Processing log")
        log_title.setObjectName("sectionTitle")
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(2000)
        log_layout.addWidget(log_title)
        log_layout.addWidget(self.console)
        grid.addWidget(controls, 0, 0)
        grid.addWidget(log_panel, 0, 1)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 3)
        return page

    def queue_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 18, 0, 0)
        layout.setSpacing(18)
        entry = QFrame()
        entry.setObjectName("panel")
        grid = QGridLayout(entry)
        grid.setContentsMargins(22, 18, 22, 18)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self.queue_account = QComboBox()
        self.queue_video = QLineEdit()
        self.queue_video.setPlaceholderText("Compliant MP4 rendition")
        browse = QPushButton("Browse")
        browse.clicked.connect(self.choose_queue_video)
        video_row = QHBoxLayout()
        video_row.addWidget(self.queue_video, 1)
        video_row.addWidget(browse)
        self.run_at = QDateTimeEdit()
        self.run_at.setCalendarPopup(True)
        self.run_at.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.run_at.setDateTime(datetime.now() + timedelta(minutes=10))
        self.caption = QLineEdit()
        self.caption.setPlaceholderText("Approved caption")
        self.repeat = QCheckBox("Repeat daily")
        queue_button = QPushButton("Queue deployment")
        queue_button.setObjectName("primaryButton")
        queue_button.clicked.connect(self.queue_deployment)
        grid.addWidget(QLabel("Profile"), 0, 0)
        grid.addWidget(QLabel("Video"), 0, 1)
        grid.addWidget(QLabel("Deployment time"), 0, 2)
        grid.addWidget(self.queue_account, 1, 0)
        grid.addLayout(video_row, 1, 1)
        grid.addWidget(self.run_at, 1, 2)
        grid.addWidget(QLabel("Caption"), 2, 0)
        grid.addWidget(self.caption, 3, 0, 1, 2)
        grid.addWidget(self.repeat, 3, 2)
        grid.addWidget(queue_button, 3, 3)
        grid.setColumnStretch(1, 2)
        layout.addWidget(entry)
        toolbar = QHBoxLayout()
        title = QLabel("23-hour guarded pipeline")
        title.setObjectName("sectionTitle")
        toolbar.addWidget(title)
        toolbar.addStretch()
        remove = QPushButton("Remove selected")
        remove.setObjectName("quietButton")
        remove.clicked.connect(self.remove_job)
        toolbar.addWidget(remove)
        run = QPushButton("Run due jobs")
        run.clicked.connect(self.run_due_jobs)
        toolbar.addWidget(run)
        layout.addLayout(toolbar)
        self.jobs = QTableWidget(0, 6)
        self.jobs.setHorizontalHeaderLabels(["Profile", "Asset", "Next run", "Cadence", "State", "Publish ID"])
        self.configure_table(self.jobs, stretch_column=1)
        layout.addWidget(self.jobs, 1)
        return page

    @staticmethod
    def configure_table(table: QTableWidget, stretch_column: int) -> None:
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        for column in range(table.columnCount()):
            mode = QHeaderView.Stretch if column == stretch_column else QHeaderView.ResizeToContents
            table.horizontalHeader().setSectionResizeMode(column, mode)

    def apply_theme(self) -> None:
        palette = QPalette()
        for role, color in (
            (QPalette.Window, "#11130f"), (QPalette.WindowText, "#ebe9df"),
            (QPalette.Base, "#171a15"), (QPalette.AlternateBase, "#1b1f18"),
            (QPalette.Text, "#ebe9df"), (QPalette.Button, "#24291f"),
            (QPalette.ButtonText, "#ebe9df"), (QPalette.Highlight, "#c7f36b"),
            (QPalette.HighlightedText, "#12150f"),
        ):
            palette.setColor(role, QColor(color))
        self.setPalette(palette)
        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #11130f; color: #ebe9df; }
            QLabel#eyebrow { color: #c7f36b; font-size: 11px; font-weight: 700; letter-spacing: 2px; }
            QLabel#title { color: #f0eee5; font-size: 28px; font-weight: 650; }
            QLabel#sectionTitle { color: #f0eee5; font-size: 18px; font-weight: 650; }
            QLabel#muted { color: #a8ad9f; }
            QLabel#statusPill { background: #1f2917; color: #c7f36b; border: 1px solid #39472b; border-radius: 15px; padding: 7px 12px; font-size: 10px; font-weight: 700; }
            QFrame#panel { background: #181b16; border: 1px solid #2d3228; border-radius: 12px; }
            QTabWidget::pane { border: 0; }
            QTabBar::tab { background: transparent; color: #969c8d; padding: 11px 18px; margin-right: 4px; border-bottom: 2px solid transparent; }
            QTabBar::tab:hover { color: #dad9d0; }
            QTabBar::tab:selected { color: #f0eee5; border-bottom: 2px solid #c7f36b; }
            QLineEdit, QSpinBox, QComboBox, QDateTimeEdit, QPlainTextEdit { background: #141712; color: #ebe9df; border: 1px solid #343a2e; border-radius: 7px; padding: 9px 10px; selection-background-color: #c7f36b; selection-color: #12150f; }
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QDateTimeEdit:focus, QPlainTextEdit:focus { border: 2px solid #98bd4f; padding: 8px 9px; }
            QLineEdit:read-only { color: #a8ad9f; background: #151813; }
            QPushButton { min-height: 40px; background: #24291f; color: #e7e5dc; border: 1px solid #373d31; border-radius: 7px; padding: 0 15px; font-weight: 600; }
            QPushButton:hover { background: #2c3325; border-color: #4a5340; }
            QPushButton:pressed { background: #1d2119; }
            QPushButton:disabled { color: #686d62; background: #1a1d17; border-color: #282c24; }
            QPushButton#primaryButton { background: #c7f36b; color: #15180f; border-color: #c7f36b; font-weight: 750; }
            QPushButton#primaryButton:hover { background: #d4fb81; border-color: #d4fb81; }
            QPushButton#quietButton { background: transparent; color: #b9bdb1; }
            QTableWidget { background: #151813; alternate-background-color: #191d17; border: 1px solid #2d3228; border-radius: 9px; gridline-color: #292e25; selection-background-color: #29331f; selection-color: #f0eee5; }
            QHeaderView::section { background: #1d211a; color: #9fa596; border: 0; border-bottom: 1px solid #343a2e; padding: 10px; font-size: 11px; font-weight: 700; }
            QTableWidget::item { padding: 9px; }
            QProgressBar { min-height: 20px; background: #1b1f18; color: #dfe2d7; border: 1px solid #30362b; border-radius: 6px; text-align: center; }
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

    def error(self, title: str, details: str) -> None:
        self.logger.error("%s: %s", title, details)
        final_line = details.strip().splitlines()[-1] if details.strip() else "Unknown error"
        self.log(f"ERROR  {final_line}")
        QMessageBox.critical(self, title, final_line)

    @staticmethod
    def selected_id(table: QTableWidget) -> str:
        row = table.currentRow()
        if row < 0 or not table.item(row, 0):
            return ""
        return table.item(row, 0).data(Qt.UserRole) or ""

    def refresh(self) -> None:
        state = self.registry.snapshot()
        self.accounts.setRowCount(len(state["accounts"]))
        self.queue_account.clear()
        names: dict[str, str] = {}
        for row, account in enumerate(state["accounts"]):
            names[account["id"]] = account["name"]
            health = "Refresh soon" if from_iso(account["token_expires_at"]) <= now_utc() + timedelta(minutes=5) else "Ready"
            values = (
                account["name"], account["platform"], health,
                "Gateway" if account.get("proxy") else "Direct",
                from_iso(account["created_at"]).astimezone().strftime("%Y-%m-%d"),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, account["id"])
                self.accounts.setItem(row, column, item)
            self.queue_account.addItem(account["name"], account["id"])

        ordered = sorted(state["jobs"], key=lambda item: item["run_at"])
        self.jobs.setRowCount(len(ordered))
        for row, job in enumerate(ordered):
            values = (
                names.get(job["account_id"], "Removed profile"), Path(job["video"]).name,
                from_iso(job["run_at"]).astimezone().strftime("%Y-%m-%d %H:%M"),
                "Daily" if job["repeat_daily"] else "Once", job["status"].title(),
                job.get("publish_id", "")[:18],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, job["id"])
                if job.get("last_error"):
                    item.setToolTip(job["last_error"])
                self.jobs.setItem(row, column, item)
        self.status.setText(
            f"{len(state['accounts'])} PROFILES / {len(ordered)} JOBS / "
            f"{len(state['deliveries'])} DELIVERIES"
        )

    def add_account(self) -> None:
        name, access, refresh = (
            self.account_name.text().strip(), self.access_token.text().strip(),
            self.refresh_token.text().strip(),
        )
        if not name or not access or not refresh:
            self.error("Missing details", "Profile name, access token, and refresh token are required")
            return
        try:
            if self.proxy.text().strip():
                TikTokPostingClient.normalize_proxy(self.proxy.text())
            account = self.registry.add_account(name, self.platform.currentText(), self.proxy.text())
            try:
                self.vault.save(account["id"], access, refresh)
            except Exception:
                self.registry.remove_account(account["id"])
                raise
            for field in (self.account_name, self.access_token, self.refresh_token, self.proxy):
                field.clear()
            self.log(f"Added authorized profile {name}")
            self.refresh()
        except Exception as exc:
            self.error("Could not add profile", str(exc))

    def remove_account(self) -> None:
        account_id = self.selected_id(self.accounts)
        if not account_id:
            self.error("Nothing selected", "Select a profile first")
            return
        self.registry.remove_account(account_id)
        self.vault.remove(account_id)
        self.log("Removed profile and its queued deployments")
        self.refresh()

    def choose_master(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select master media", "", "Media (*.mp4 *.mov *.mkv *.webm)")
        if path:
            self.master.setText(path)
            if not self.output_dir.text():
                source = Path(path)
                self.output_dir.setText(str(source.parent / f"{source.stem}-renditions"))

    def choose_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select output folder")
        if path:
            self.output_dir.setText(path)

    def start_batch(self) -> None:
        source = Path(self.master.text())
        target = Path(self.output_dir.text())
        if not source.is_file() or not self.output_dir.text().strip():
            self.error("Missing paths", "Choose an existing master file and output folder")
            return
        self.render_button.setEnabled(False)
        self.progress.setValue(0)
        signals = self.runner.start(
            lambda channel: self.encoder.encode(source, target, self.batch_size.value(), channel)
        )
        signals.log.connect(self.log)
        signals.progress.connect(self.progress.setValue)
        signals.result.connect(self.batch_finished)
        signals.error.connect(lambda details: self.error("Batch failed", details))
        signals.finished.connect(lambda: self.render_button.setEnabled(True))

    def batch_finished(self, result: object) -> None:
        self.last_outputs = list(result or [])
        if self.last_outputs:
            self.queue_video.setText(self.last_outputs[0])
        self.log(f"Completed {len(self.last_outputs)} compliant renditions")

    def choose_queue_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select deployment asset", "", "MP4 (*.mp4)")
        if path:
            self.queue_video.setText(path)

    def queue_deployment(self) -> None:
        account_id = self.queue_account.currentData()
        video = Path(self.queue_video.text())
        caption = self.caption.text().strip()
        local_time = self.run_at.dateTime().toPython()
        if local_time.tzinfo is None:
            local_time = local_time.astimezone()
        if not account_id or not video.is_file() or video.suffix.lower() != ".mp4" or not caption:
            self.error("Incomplete deployment", "Choose a profile, an existing MP4, and a caption")
            return
        try:
            self.registry.queue_job(
                account_id, video, caption, local_time.astimezone(UTC), self.repeat.isChecked()
            )
            self.caption.clear()
            self.log("Queued deployment after deterministic 23-hour verification")
            self.refresh()
        except Exception as exc:
            self.error("Could not queue deployment", str(exc))

    def remove_job(self) -> None:
        job_id = self.selected_id(self.jobs)
        if not job_id:
            self.error("Nothing selected", "Select a deployment first")
            return
        if job_id in self.active_jobs:
            self.error("Deployment is active", "Wait for the current network request to finish")
            return
        self.registry.remove_job(job_id)
        self.log("Removed deployment")
        self.refresh()

    def run_due_jobs(self) -> None:
        state = self.registry.snapshot()
        due_ids = [
            job["id"] for job in state["jobs"]
            if job["status"] == "queued" and from_iso(job["run_at"]) <= now_utc()
            and job["id"] not in self.active_jobs
        ]
        for job_id in due_ids:
            try:
                job, account = self.registry.claim_due_job(job_id)
            except Exception as exc:
                self.registry.fail_job(job_id, str(exc))
                self.log(f"Compliance guard blocked deployment: {exc}")
                continue
            self.active_jobs.add(job_id)
            signals = self.runner.start(
                lambda channel, j=job, a=account: self.client.publish(
                    a, Path(j["video"]), j["caption"], channel
                )
            )
            signals.log.connect(self.log)
            signals.progress.connect(lambda value, key=job_id: self.log(f"Upload {key[:6]}: {value}%"))
            signals.result.connect(lambda publish_id, key=job_id: self.job_succeeded(key, str(publish_id)))
            signals.error.connect(lambda details, key=job_id: self.job_failed(key, details))
            signals.finished.connect(lambda key=job_id: self.job_finished(key))
        self.refresh()

    def job_succeeded(self, job_id: str, publish_id: str) -> None:
        self.registry.complete_job(job_id, publish_id)
        self.log(f"TikTok accepted deployment {publish_id}; delivery history updated")
        self.refresh()

    def job_failed(self, job_id: str, details: str) -> None:
        final_line = details.strip().splitlines()[-1] if details.strip() else "Unknown upload error"
        self.registry.fail_job(job_id, final_line)
        self.error("Deployment failed", details)
        self.refresh()

    def job_finished(self, job_id: str) -> None:
        self.active_jobs.discard(job_id)
        self.refresh()


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
