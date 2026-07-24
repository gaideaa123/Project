from __future__ import annotations

"""SignalDesk Studio: hardened single-file TikTok publisher.

Runtime dependencies:
    pip install PySide6 requests keyring platformdirs

The application uses TikTok's documented Login Kit and Content Posting API.
Public posting remains subject to TikTok app review and user consent.
"""

import contextlib
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import shutil
import string
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

import keyring
import requests
from platformdirs import user_data_dir
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PySide6.QtCore import QObject, QDateTime, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateTimeEdit, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

APP_NAME = "SignalDesk Studio"
APP_SLUG = "signaldesk-studio"
UTC = timezone.utc
POST_WINDOW = timedelta(hours=23)
TIKTOK_API = "https://open.tiktokapis.com"
TIKTOK_AUTH = "https://www.tiktok.com/v2/auth/authorize/"
KEYRING_SERVICE = "signaldesk-studio"
STATE_VERSION = 3


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def app_data_dir() -> Path:
    path = Path(user_data_dir(APP_SLUG, "SignalDesk"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_logger(folder: Path) -> logging.Logger:
    logger = logging.getLogger(APP_SLUG)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            folder / "studio_production.log", maxBytes=5_000_000,
            backupCount=5, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
        ))
        logger.addHandler(handler)
    return logger


DATA_DIR = app_data_dir()
LOGGER = build_logger(DATA_DIR)


class StudioError(RuntimeError):
    pass


class StateError(StudioError):
    pass


class ApiError(StudioError):
    pass


class Cancelled(StudioError):
    pass


class ProcessFileLock:
    """Small cross-process lock based on atomic O_EXCL creation."""

    def __init__(self, path: Path, timeout: float = 10.0, stale_after: float = 900.0):
        self.path = path
        self.timeout = timeout
        self.stale_after = stale_after
        self.fd: int | None = None

    def acquire(self) -> bool:
        deadline = time.monotonic() + self.timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while time.monotonic() < deadline:
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                payload = json.dumps({"pid": os.getpid(), "created": time.time()}).encode()
                os.write(self.fd, payload)
                os.fsync(self.fd)
                return True
            except FileExistsError:
                with contextlib.suppress(OSError, ValueError, json.JSONDecodeError):
                    age = time.time() - self.path.stat().st_mtime
                    if age > self.stale_after:
                        self.path.unlink()
                        continue
                time.sleep(0.1)
        return False

    def release(self) -> None:
        if self.fd is not None:
            with contextlib.suppress(OSError):
                os.close(self.fd)
            self.fd = None
        with contextlib.suppress(OSError):
            self.path.unlink()

    def __enter__(self) -> "ProcessFileLock":
        if not self.acquire():
            raise StateError(f"Lock timeout: {self.path.name}")
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


class AtomicRegistry:
    """Thread-safe and process-safe JSON registry with atomic replacement."""

    def __init__(self, path: Path):
        self.path = path
        self.backup = path.with_suffix(".json.bak")
        self.lock_path = path.with_suffix(".json.lock")
        self.thread_lock = threading.RLock()
        if not path.exists():
            self._atomic_write(self._empty())

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"version": STATE_VERSION, "accounts": [], "jobs": []}

    def _read_unlocked(self) -> dict[str, Any]:
        sources = (self.path, self.backup)
        last_error: Exception | None = None
        for source in sources:
            if not source.exists():
                continue
            try:
                data = json.loads(source.read_text(encoding="utf-8"))
                if not isinstance(data.get("accounts"), list) or not isinstance(data.get("jobs"), list):
                    raise ValueError("invalid state schema")
                data["version"] = STATE_VERSION
                return data
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                LOGGER.exception("State read failed for %s", source.name)
        raise StateError(f"State is unreadable: {last_error}")

    def _atomic_write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="automation-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            if self.path.exists():
                shutil.copy2(self.path, self.backup)
            os.replace(temporary, self.path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(temporary)

    def snapshot(self) -> dict[str, Any]:
        with self.thread_lock, ProcessFileLock(self.lock_path):
            return json.loads(json.dumps(self._read_unlocked()))

    def mutate(self, operation: Callable[[dict[str, Any]], Any]) -> Any:
        with self.thread_lock, ProcessFileLock(self.lock_path):
            state = self._read_unlocked()
            result = operation(state)
            self._atomic_write(state)
            return result

    def add_account(self, name: str) -> dict[str, Any]:
        clean = name.strip()
        if not clean:
            raise StateError("Profile name is required")
        account = {
            "id": uuid.uuid4().hex, "name": clean, "platform": "TikTok",
            "created_at": iso(utc_now()), "token_expires_at": "",
            "last_post_at": "", "last_status": "Connected",
        }
        def operation(state: dict[str, Any]) -> dict[str, Any]:
            if any(a["name"].casefold() == clean.casefold() for a in state["accounts"]):
                raise StateError("Profile names must be unique")
            state["accounts"].append(account)
            return account
        return self.mutate(operation)

    def update_account(self, account_id: str, **changes: Any) -> None:
        def operation(state: dict[str, Any]) -> None:
            account = next((a for a in state["accounts"] if a["id"] == account_id), None)
            if not account:
                raise StateError("Profile no longer exists")
            account.update(changes)
        self.mutate(operation)

    def delete_account(self, account_id: str) -> None:
        def operation(state: dict[str, Any]) -> None:
            if any(j["account_id"] == account_id and j["status"] == "running" for j in state["jobs"]):
                raise StateError("A running profile cannot be removed")
            state["accounts"] = [a for a in state["accounts"] if a["id"] != account_id]
            state["jobs"] = [j for j in state["jobs"] if j["account_id"] != account_id]
        self.mutate(operation)

    @staticmethod
    def _assert_window(state: dict[str, Any], account_id: str, planned: datetime) -> None:
        account = next((a for a in state["accounts"] if a["id"] == account_id), None)
        if not account:
            raise StateError("Select a valid profile")
        if account.get("last_post_at"):
            if abs(planned - parse_iso(account["last_post_at"])) < POST_WINDOW:
                raise StateError("This profile is inside its protected 23-hour window")
        for job in state["jobs"]:
            if job["account_id"] != account_id or job["status"] not in {"queued", "running", "processing"}:
                continue
            if abs(planned - parse_iso(job["run_at"])) < POST_WINDOW:
                raise StateError("Another active post exists within 23 hours")

    def add_job(self, account_id: str, video: str, caption: str,
                run_at: datetime, privacy: str) -> dict[str, Any]:
        path = Path(video).expanduser().resolve()
        if not path.is_file():
            raise StateError("Choose an existing video")
        if path.suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm"}:
            raise StateError("Unsupported video container")
        job = {
            "id": uuid.uuid4().hex, "account_id": account_id,
            "video_path": str(path), "caption": caption.strip()[:2200],
            "run_at": iso(run_at), "privacy": privacy, "status": "queued",
            "progress": 0, "publish_id": "", "server_status": "",
            "last_error": "", "attempts": 0, "created_at": iso(utc_now()),
        }
        def operation(state: dict[str, Any]) -> dict[str, Any]:
            self._assert_window(state, account_id, run_at.astimezone(UTC))
            state["jobs"].append(job)
            return job
        return self.mutate(operation)

    def claim_job(self, job_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        now = utc_now()
        def operation(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
            job = next((j for j in state["jobs"] if j["id"] == job_id), None)
            if not job or job["status"] != "queued" or parse_iso(job["run_at"]) > now:
                raise StateError("Job is not claimable")
            account = next((a for a in state["accounts"] if a["id"] == job["account_id"]), None)
            if not account:
                raise StateError("Profile was removed")
            if any(j["account_id"] == account["id"] and j["status"] in {"running", "processing"}
                   and j["id"] != job_id for j in state["jobs"]):
                raise StateError("Profile already has a running upload")
            if account.get("last_post_at") and now - parse_iso(account["last_post_at"]) < POST_WINDOW:
                raise StateError("23-hour guard blocked this upload")
            job.update(status="running", progress=1, last_error="", attempts=job.get("attempts", 0) + 1)
            return json.loads(json.dumps(job)), json.loads(json.dumps(account))
        return self.mutate(operation)

    def update_job(self, job_id: str, **changes: Any) -> None:
        def operation(state: dict[str, Any]) -> None:
            job = next((j for j in state["jobs"] if j["id"] == job_id), None)
            if job:
                job.update(changes)
        self.mutate(operation)

    def complete_job(self, job_id: str, publish_id: str, server_status: str) -> None:
        submitted = utc_now()
        def operation(state: dict[str, Any]) -> None:
            job = next(j for j in state["jobs"] if j["id"] == job_id)
            account = next(a for a in state["accounts"] if a["id"] == job["account_id"])
            job.update(status="published", progress=100, publish_id=publish_id,
                       server_status=server_status, last_error="")
            account.update(last_post_at=iso(submitted), last_status=server_status)
        self.mutate(operation)

    def fail_job(self, job_id: str, message: str) -> None:
        self.update_job(job_id, status="failed", last_error=message[:1200])

    def recover_interrupted(self) -> None:
        def operation(state: dict[str, Any]) -> None:
            for job in state["jobs"]:
                if job["status"] in {"running", "processing"}:
                    job.update(status="queued", last_error="Recovered after interrupted shutdown")
        self.mutate(operation)


class SecureVault:
    """OS-keychain storage. Values are never logged or persisted in JSON."""

    def _set(self, key: str, value: str) -> None:
        try:
            keyring.set_password(KEYRING_SERVICE, key, value)
        except Exception as exc:
            LOGGER.exception("Keychain write failed")
            raise StudioError("The operating-system keychain rejected the credential") from exc

    def _get(self, key: str) -> str:
        try:
            return keyring.get_password(KEYRING_SERVICE, key) or ""
        except Exception as exc:
            LOGGER.exception("Keychain read failed")
            raise StudioError("The operating-system keychain is unavailable") from exc

    def set_app(self, client_key: str, client_secret: str, redirect_uri: str) -> None:
        self._set("app:client_key", client_key)
        self._set("app:client_secret", client_secret)
        self._set("app:redirect_uri", redirect_uri)

    def app(self) -> tuple[str, str, str]:
        return self._get("app:client_key"), self._get("app:client_secret"), self._get("app:redirect_uri")

    def set_tokens(self, account_id: str, access: str, refresh: str) -> None:
        self._set(f"{account_id}:access", access)
        self._set(f"{account_id}:refresh", refresh)

    def tokens(self, account_id: str) -> tuple[str, str]:
        return self._get(f"{account_id}:access"), self._get(f"{account_id}:refresh")

    def delete_account(self, account_id: str) -> None:
        for suffix in ("access", "refresh"):
            with contextlib.suppress(Exception):
                keyring.delete_password(KEYRING_SERVICE, f"{account_id}:{suffix}")


class ResilientHttp:
    def __init__(self):
        retry = Retry(
            total=5, connect=5, read=5, status=5, backoff_factor=0.8,
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST", "PUT"}),
            respect_retry_after_header=True, raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": f"{APP_NAME}/3.0"})
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.direct = requests.Session()
        self.direct.trust_env = False
        self.direct.mount("https://", adapter)
        self.direct.mount("http://", adapter)

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", (15, 120))
        try:
            return self.session.request(method, url, **kwargs)
        except requests.exceptions.ProxyError:
            LOGGER.warning("Configured proxy failed; retrying direct connection")
            return self.direct.request(method, url, **kwargs)
        except requests.RequestException as exc:
            raise ApiError(f"Network request failed: {type(exc).__name__}") from exc


class TikTokClient:
    TERMINAL_SUCCESS = {"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"}
    TERMINAL_FAILURE = {"FAILED", "PUBLISH_FAILED", "DOWNLOAD_FAILED"}

    def __init__(self, registry: AtomicRegistry, vault: SecureVault):
        self.registry = registry
        self.vault = vault
        self.http = ResilientHttp()

    @staticmethod
    def payload(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ApiError(f"TikTok returned non-JSON HTTP {response.status_code}") from exc
        if not response.ok:
            error = data.get("error", {})
            raise ApiError(f"TikTok HTTP {response.status_code}: {error.get('message') or error.get('code') or 'request failed'}")
        error = data.get("error") or {}
        if error.get("code") not in (None, "", "ok", 0):
            raise ApiError(f"TikTok API: {error.get('message') or error.get('code')}")
        return data

    def access_token(self, account: dict[str, Any]) -> str:
        access, refresh = self.vault.tokens(account["id"])
        if not access:
            raise ApiError("This profile has no OAuth access token")
        expiry = account.get("token_expires_at")
        if expiry and parse_iso(expiry) > utc_now() + timedelta(minutes=5):
            return access
        client_key, client_secret, _ = self.vault.app()
        if not all((client_key, client_secret, refresh)):
            raise ApiError("Token refresh credentials are incomplete")
        response = self.http.request(
            "POST", f"{TIKTOK_API}/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"client_key": client_key, "client_secret": client_secret,
                  "grant_type": "refresh_token", "refresh_token": refresh},
            timeout=(15, 45),
        )
        data = self.payload(response)
        access = data["access_token"]
        self.vault.set_tokens(account["id"], access, data.get("refresh_token", refresh))
        self.registry.update_account(
            account["id"], token_expires_at=iso(utc_now() + timedelta(seconds=int(data.get("expires_in", 86400))))
        )
        return access

    @staticmethod
    def chunk_plan(size: int) -> tuple[int, int]:
        if size <= 0:
            raise ApiError("Video is empty")
        mib = 1024 * 1024
        if size <= 64 * mib:
            return size, 1
        chunk = 10 * mib
        count = (size + chunk - 1) // chunk
        if count > 1000:
            chunk = 64 * mib
            count = (size + chunk - 1) // chunk
        if count > 1000:
            raise ApiError("Video exceeds the supported chunk count")
        return chunk, count

    def creator_info(self, token: str) -> dict[str, Any]:
        response = self.http.request(
            "POST", f"{TIKTOK_API}/v2/post/publish/creator_info/query/",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json={}, timeout=(15, 45),
        )
        return self.payload(response).get("data", {})

    def upload(self, account: dict[str, Any], job: dict[str, Any],
               progress: Callable[[int, str], None], cancelled: Callable[[], bool]) -> str:
        video = Path(job["video_path"])
        validate_media(video)
        token = self.access_token(account)
        creator = self.creator_info(token)
        allowed = creator.get("privacy_level_options") or ["SELF_ONLY"]
        privacy = job.get("privacy", "SELF_ONLY")
        if privacy not in allowed:
            privacy = "SELF_ONLY" if "SELF_ONLY" in allowed else allowed[0]
        size = video.stat().st_size
        chunk_size, chunk_count = self.chunk_plan(size)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
        init = self.http.request(
            "POST", f"{TIKTOK_API}/v2/post/publish/video/init/", headers=headers,
            json={
                "post_info": {"title": job["caption"], "privacy_level": privacy,
                              "disable_duet": False, "disable_comment": False,
                              "disable_stitch": False, "video_cover_timestamp_ms": 1000},
                "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                "chunk_size": chunk_size, "total_chunk_count": chunk_count},
            }, timeout=(15, 60),
        )
        initialized = self.payload(init).get("data", {})
        upload_url, publish_id = initialized.get("upload_url"), initialized.get("publish_id")
        if not upload_url or not publish_id:
            raise ApiError("TikTok did not return an upload URL and publish ID")
        sent = 0
        with video.open("rb") as handle:
            for index in range(chunk_count):
                if cancelled():
                    raise Cancelled("Upload cancelled")
                amount = min(chunk_size, size - sent)
                body = handle.read(amount)
                if len(body) != amount:
                    raise ApiError("Video changed or became unreadable during upload")
                end = sent + amount - 1
                response = self.http.request(
                    "PUT", upload_url, data=body,
                    headers={"Content-Type": "video/mp4", "Content-Length": str(amount),
                             "Content-Range": f"bytes {sent}-{end}/{size}"},
                    timeout=(30, 240),
                )
                if not response.ok:
                    raise ApiError(f"Chunk {index + 1} failed with HTTP {response.status_code}")
                sent = end + 1
                progress(5 + round(70 * sent / size), f"Uploaded chunk {index + 1}/{chunk_count}")
        return publish_id

    def poll(self, account: dict[str, Any], publish_id: str,
             progress: Callable[[int, str], None], cancelled: Callable[[], bool],
             timeout_seconds: int = 900) -> str:
        token = self.access_token(account)
        deadline = time.monotonic() + timeout_seconds
        interval = 2.0
        while time.monotonic() < deadline:
            if cancelled():
                raise Cancelled("Status polling cancelled")
            response = self.http.request(
                "POST", f"{TIKTOK_API}/v2/post/publish/status/fetch/",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"publish_id": publish_id}, timeout=(15, 45),
            )
            data = self.payload(response).get("data", {})
            status = str(data.get("status", "PROCESSING_UPLOAD"))
            uploaded = int(data.get("uploaded_bytes", 0) or 0)
            progress(min(99, 78 + int((time.monotonic() % 20))), status.replace("_", " ").title())
            if status in self.TERMINAL_SUCCESS:
                return status
            if status in self.TERMINAL_FAILURE:
                reasons = data.get("fail_reason") or data.get("publicaly_available_post_id") or "TikTok processing failed"
                raise ApiError(str(reasons))
            LOGGER.info("Publish status %s, uploaded_bytes=%s", status, uploaded)
            time.sleep(interval)
            interval = min(15.0, interval * 1.35)
        raise ApiError("Publishing status timed out after 15 minutes")


def validate_media(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise StudioError("Video is missing or empty")
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        LOGGER.warning("FFprobe is unavailable; deep media validation skipped")
        return
    try:
        completed = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,width,height,duration",
             "-of", "json", str(path)], capture_output=True, text=True,
            timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StudioError("FFprobe could not inspect the video") from exc
    if completed.returncode != 0:
        LOGGER.error("FFprobe rejected media: %s", completed.stderr[:1000])
        raise StudioError("Video contains unreadable or corrupted frames")
    try:
        streams = json.loads(completed.stdout).get("streams", [])
    except json.JSONDecodeError as exc:
        raise StudioError("FFprobe returned invalid media metadata") from exc
    if not streams or not streams[0].get("codec_name"):
        raise StudioError("No valid video stream was found")


@dataclass
class OAuthResult:
    access_token: str
    refresh_token: str
    expires_in: int


class OAuthFlow:
    def __init__(self, vault: SecureVault):
        self.vault = vault
        self.http = ResilientHttp()

    def authorize(self, cancelled: Callable[[], bool]) -> OAuthResult:
        client_key, client_secret, redirect_uri = self.vault.app()
        if not all((client_key, client_secret, redirect_uri)):
            raise StudioError("Save Client Key, Client Secret, and Redirect URI first")
        parsed = urllib.parse.urlparse(redirect_uri)
        if parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.port:
            raise StudioError("Redirect URI must use localhost with an explicit port")
        state = secrets.token_urlsafe(32)
        alphabet = string.ascii_letters + string.digits + "-._~"
        verifier = "".join(secrets.choice(alphabet) for _ in range(64))
        challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
        result: dict[str, str] = {}
        event = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if query.get("state", [""])[0] != state:
                    self.send_response(400); self.end_headers(); event.set(); return
                result["code"] = query.get("code", [""])[0]
                result["error"] = query.get("error_description", query.get("error", [""]))[0]
                body = b"<html><body style='font-family:system-ui;background:#111;color:#eee;padding:48px'>Authorization received. You may close this tab.</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body); event.set()

            def log_message(self, *_: object) -> None:
                return

        server = ThreadingHTTPServer((parsed.hostname, parsed.port), Handler)
        server.timeout = 0.5
        params = {"client_key": client_key, "scope": "user.info.basic,video.publish",
                  "response_type": "code", "redirect_uri": redirect_uri, "state": state,
                  "code_challenge": challenge, "code_challenge_method": "S256"}
        webbrowser.open(TIKTOK_AUTH + "?" + urllib.parse.urlencode(params))
        deadline = time.monotonic() + 300
        try:
            while not event.is_set() and time.monotonic() < deadline:
                if cancelled():
                    raise Cancelled("Authorization cancelled")
                server.handle_request()
        finally:
            server.server_close()
        if result.get("error"):
            raise ApiError(result["error"])
        code = result.get("code")
        if not code:
            raise ApiError("Authorization timed out or returned no code")
        response = self.http.request(
            "POST", f"{TIKTOK_API}/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"client_key": client_key, "client_secret": client_secret,
                  "code": code, "grant_type": "authorization_code",
                  "redirect_uri": redirect_uri, "code_verifier": verifier}, timeout=(15, 45),
        )
        data = TikTokClient.payload(response)
        return OAuthResult(data["access_token"], data.get("refresh_token", ""), int(data.get("expires_in", 86400)))


class UploadThread(QThread):
    progress_changed = Signal(str, int, str)
    succeeded = Signal(str, str, str)
    failed = Signal(str, str)

    def __init__(self, registry: AtomicRegistry, vault: SecureVault,
                 job: dict[str, Any], account: dict[str, Any]):
        super().__init__()
        self.registry, self.vault = registry, vault
        self.job, self.account = job, account
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        account_lock = DATA_DIR / "locks" / f"account-{self.account['id']}.lock"
        lease = ProcessFileLock(account_lock, timeout=1.0, stale_after=1800)
        try:
            if not lease.acquire():
                raise StateError("Another process owns this profile upload lock")
            client = TikTokClient(self.registry, self.vault)
            def report(value: int, text: str) -> None:
                self.registry.update_job(self.job["id"], progress=value, server_status=text)
                self.progress_changed.emit(self.job["id"], value, text)
            publish_id = client.upload(self.account, self.job, report, self._cancel.is_set)
            self.registry.update_job(self.job["id"], status="processing", publish_id=publish_id, progress=78)
            status = client.poll(self.account, publish_id, report, self._cancel.is_set)
            self.registry.complete_job(self.job["id"], publish_id, status)
            self.succeeded.emit(self.job["id"], publish_id, status)
        except Exception as exc:
            message = str(exc) or type(exc).__name__
            LOGGER.exception("Upload job failed: %s", self.job["id"])
            self.registry.fail_job(self.job["id"], message)
            self.failed.emit(self.job["id"], message)
        finally:
            lease.release()


class OAuthThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, vault: SecureVault):
        super().__init__(); self.vault = vault; self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            self.succeeded.emit(OAuthFlow(self.vault).authorize(self._cancel.is_set))
        except Exception as exc:
            LOGGER.exception("OAuth flow failed")
            self.failed.emit(str(exc) or type(exc).__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.registry = AtomicRegistry(DATA_DIR / "automation_state.json")
        self.vault = SecureVault()
        self.registry.recover_interrupted()
        self.workers: dict[str, UploadThread] = {}
        self.oauth_worker: OAuthThread | None = None
        self.setWindowTitle(APP_NAME)
        self.resize(1260, 820)
        self.setMinimumSize(980, 680)
        self.build_ui(); self.apply_theme(); self.refresh()
        self.scheduler = QTimer(self)
        self.scheduler.timeout.connect(self.run_due)
        self.scheduler.start(15_000)
        QTimer.singleShot(1500, self.run_due)

    def build_ui(self) -> None:
        root = QWidget(); outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 28); outer.setSpacing(18)
        header = QHBoxLayout(); brand = QVBoxLayout(); brand.setSpacing(2)
        eyebrow = QLabel("SIGNALDESK / CONTROL PLANE"); eyebrow.setObjectName("eyebrow")
        title = QLabel("Publishing without guesswork."); title.setObjectName("title")
        brand.addWidget(eyebrow); brand.addWidget(title); header.addLayout(brand); header.addStretch()
        self.global_status = QLabel("READY"); self.global_status.setObjectName("pill")
        header.addWidget(self.global_status); outer.addLayout(header)
        self.tabs = QTabWidget(); self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.accounts_page(), "Profiles")
        self.tabs.addTab(self.queue_page(), "Queue")
        self.tabs.addTab(self.settings_page(), "API settings")
        outer.addWidget(self.tabs, 1); self.setCentralWidget(root)

    def accounts_page(self) -> QWidget:
        page = QWidget(); layout = QGridLayout(page); layout.setContentsMargins(0, 18, 0, 0); layout.setHorizontalSpacing(24)
        panel = QFrame(); panel.setObjectName("panel"); formbox = QVBoxLayout(panel)
        formbox.setContentsMargins(24, 24, 24, 24); formbox.setSpacing(14)
        heading = QLabel("Authorized profiles"); heading.setObjectName("section")
        note = QLabel("OAuth credentials stay in your OS keychain. Nothing sensitive enters the state file or logs.")
        note.setWordWrap(True); note.setObjectName("muted"); formbox.addWidget(heading); formbox.addWidget(note)
        form = QFormLayout(); self.profile_name = QLineEdit(); self.profile_name.setPlaceholderText("Brand EU")
        form.addRow("Profile name", self.profile_name); formbox.addLayout(form)
        buttons = QHBoxLayout(); add = QPushButton("Add profile"); add.setObjectName("primary"); add.clicked.connect(self.add_profile)
        auth = QPushButton("Authorize selected"); auth.clicked.connect(self.authorize_selected)
        buttons.addWidget(add); buttons.addWidget(auth); formbox.addLayout(buttons); formbox.addStretch()
        right = QVBoxLayout(); bar = QHBoxLayout(); label = QLabel("Profile matrix"); label.setObjectName("section")
        remove = QPushButton("Remove"); remove.clicked.connect(self.remove_profile)
        bar.addWidget(label); bar.addStretch(); bar.addWidget(remove); right.addLayout(bar)
        self.accounts = QTableWidget(0, 5); self.accounts.setHorizontalHeaderLabels(["Profile", "Platform", "OAuth", "Last post", "State"])
        self.configure_table(self.accounts); right.addWidget(self.accounts)
        layout.addWidget(panel, 0, 0); layout.addLayout(right, 0, 1); layout.setColumnStretch(1, 1)
        return page

    def queue_page(self) -> QWidget:
        page = QWidget(); outer = QVBoxLayout(page); outer.setContentsMargins(0, 18, 0, 0); outer.setSpacing(18)
        controls = QFrame(); controls.setObjectName("panel"); grid = QGridLayout(controls)
        grid.setContentsMargins(24, 22, 24, 22); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(12)
        self.account_combo = QComboBox(); self.video = QLineEdit(); self.video.setPlaceholderText("Select a local video")
        browse = QPushButton("Browse"); browse.clicked.connect(self.choose_video)
        self.caption = QLineEdit(); self.caption.setPlaceholderText("Caption, up to 2,200 characters")
        self.run_at = QDateTimeEdit(QDateTime.currentDateTime().addSecs(60)); self.run_at.setCalendarPopup(True); self.run_at.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.privacy = QComboBox(); self.privacy.addItems(["SELF_ONLY", "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR"])
        grid.addWidget(QLabel("Profile"), 0, 0); grid.addWidget(self.account_combo, 0, 1)
        grid.addWidget(QLabel("Video"), 0, 2); grid.addWidget(self.video, 0, 3); grid.addWidget(browse, 0, 4)
        grid.addWidget(QLabel("Caption"), 1, 0); grid.addWidget(self.caption, 1, 1, 1, 2)
        grid.addWidget(QLabel("Run at"), 1, 3); grid.addWidget(self.run_at, 1, 4)
        grid.addWidget(QLabel("Privacy"), 2, 0); grid.addWidget(self.privacy, 2, 1)
        queue = QPushButton("Queue post"); queue.setObjectName("primary"); queue.clicked.connect(self.queue_post)
        run = QPushButton("Run due now"); run.clicked.connect(self.run_due)
        grid.addWidget(queue, 2, 3); grid.addWidget(run, 2, 4); grid.setColumnStretch(3, 1)
        outer.addWidget(controls)
        self.jobs = QTableWidget(0, 8); self.jobs.setHorizontalHeaderLabels(["Profile", "Video", "Run at", "State", "Progress", "Server", "Attempts", "Error"])
        self.configure_table(self.jobs); outer.addWidget(self.jobs, 1)
        self.job_progress = QProgressBar(); self.job_progress.setRange(0, 100); self.job_progress.setValue(0); outer.addWidget(self.job_progress)
        return page

    def settings_page(self) -> QWidget:
        page = QWidget(); layout = QHBoxLayout(page); layout.setContentsMargins(0, 18, 0, 0)
        panel = QFrame(); panel.setObjectName("panel"); box = QVBoxLayout(panel); box.setContentsMargins(28, 26, 28, 28); box.setSpacing(16)
        title = QLabel("TikTok application credentials"); title.setObjectName("section"); box.addWidget(title)
        note = QLabel("Use a localhost redirect registered in TikTok Developer Portal, for example http://127.0.0.1:3455/callback/.")
        note.setWordWrap(True); note.setObjectName("muted"); box.addWidget(note)
        form = QFormLayout(); client_key, _, redirect = self.vault.app()
        self.client_key = QLineEdit(client_key); self.client_secret = QLineEdit(); self.client_secret.setEchoMode(QLineEdit.Password)
        self.redirect_uri = QLineEdit(redirect or "http://127.0.0.1:3455/callback/")
        form.addRow("Client Key", self.client_key); form.addRow("Client Secret", self.client_secret); form.addRow("Redirect URI", self.redirect_uri)
        box.addLayout(form); save = QPushButton("Save to OS keychain"); save.setObjectName("primary"); save.clicked.connect(self.save_settings)
        box.addWidget(save); box.addStretch(); layout.addWidget(panel, 1); layout.addStretch(1); return page

    @staticmethod
    def configure_table(table: QTableWidget) -> None:
        table.setAlternatingRowColors(True); table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers); table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)

    def apply_theme(self) -> None:
        palette = QPalette(); palette.setColor(QPalette.Window, QColor("#101312")); palette.setColor(QPalette.WindowText, QColor("#e7ece8"))
        palette.setColor(QPalette.Base, QColor("#151a18")); palette.setColor(QPalette.AlternateBase, QColor("#1a201d"))
        palette.setColor(QPalette.Text, QColor("#e7ece8")); palette.setColor(QPalette.Button, QColor("#202723")); palette.setColor(QPalette.ButtonText, QColor("#e7ece8"))
        palette.setColor(QPalette.Highlight, QColor("#71d49a")); palette.setColor(QPalette.HighlightedText, QColor("#0d1610")); self.setPalette(palette)
        self.setStyleSheet("""
            QWidget { color:#e7ece8; font-family:'Segoe UI'; font-size:13px; }
            QMainWindow { background:#101312; } QTabWidget::pane { border:0; }
            QTabBar::tab { padding:11px 18px; color:#89958e; border-bottom:2px solid transparent; }
            QTabBar::tab:selected { color:#e7ece8; border-bottom-color:#71d49a; }
            QFrame#panel { background:#171c19; border:1px solid #28312c; border-radius:12px; }
            QLabel#eyebrow { color:#71d49a; font-size:11px; font-weight:700; letter-spacing:2px; }
            QLabel#title { font-size:28px; font-weight:700; } QLabel#section { font-size:18px; font-weight:700; }
            QLabel#muted { color:#98a29c; } QLabel#pill { background:#20372a; color:#8ee0ac; padding:7px 13px; border-radius:12px; font-weight:700; }
            QLineEdit,QDateTimeEdit,QSpinBox { background:#111512; border:1px solid #344039; border-radius:7px; padding:9px; min-height:20px; }
            QLineEdit:focus,QDateTimeEdit:focus { border:1px solid #71d49a; }
            QComboBox { background:#111512; border:1px solid #344039; border-radius:7px; padding:9px 32px 9px 9px; min-height:20px; }
            QComboBox:focus { border:1px solid #71d49a; }
            QComboBox:hover { border:1px solid #5a7a6a; }
            QComboBox::drop-down { subcontrol-origin:padding; subcontrol-position:top right; width:28px; border-left:1px solid #344039; border-radius:0 7px 7px 0; background:#1e2521; }
            QComboBox::down-arrow { width:10px; height:10px; border-left:2px solid #71d49a; border-bottom:2px solid #71d49a; }
            QComboBox QAbstractItemView { background:#151a18; border:1px solid #344039; border-radius:6px; selection-background-color:#20372a; selection-color:#e7ece8; color:#e7ece8; outline:0; }
            QPushButton { background:#252d28; border:1px solid #39463e; border-radius:7px; padding:9px 14px; min-height:20px; }
            QPushButton:hover { background:#2d3831; } QPushButton:pressed { background:#1d2520; }
            QPushButton#primary { background:#71d49a; color:#102016; border:0; font-weight:700; }
            QPushButton#primary:hover { background:#82dfa6; }
            QTableWidget { background:#131714; alternate-background-color:#171c19; border:1px solid #28312c; border-radius:9px; gridline-color:#27302b; }
            QHeaderView::section { background:#1e2521; color:#aab4ae; padding:9px; border:0; border-bottom:1px solid #344039; font-weight:700; }
            QProgressBar { background:#1b211d; border:1px solid #344039; border-radius:6px; text-align:center; min-height:18px; }
            QProgressBar::chunk { background:#71d49a; border-radius:5px; }
        """)

    def selected_account_id(self) -> str:
        row = self.accounts.currentRow()
        return self.accounts.item(row, 0).data(Qt.UserRole) if row >= 0 and self.accounts.item(row, 0) else ""

    def add_profile(self) -> None:
        try:
            self.registry.add_account(self.profile_name.text()); self.profile_name.clear(); self.refresh()
        except Exception as exc: self.show_error(str(exc))

    def remove_profile(self) -> None:
        account_id = self.selected_account_id()
        if not account_id: return
        try:
            self.registry.delete_account(account_id); self.vault.delete_account(account_id); self.refresh()
        except Exception as exc: self.show_error(str(exc))

    def authorize_selected(self) -> None:
        account_id = self.selected_account_id()
        if not account_id: self.show_error("Select a profile first"); return
        if self.oauth_worker and self.oauth_worker.isRunning(): return
        self.global_status.setText("AUTHORIZING")
        worker = OAuthThread(self.vault); self.oauth_worker = worker
        worker.succeeded.connect(lambda result: self.oauth_success(account_id, result))
        worker.failed.connect(lambda text: (self.show_error(text), self.global_status.setText("READY")))
        worker.finished.connect(lambda: setattr(self, "oauth_worker", None)); worker.start()

    def oauth_success(self, account_id: str, result: OAuthResult) -> None:
        try:
            self.vault.set_tokens(account_id, result.access_token, result.refresh_token)
            self.registry.update_account(account_id, token_expires_at=iso(utc_now() + timedelta(seconds=result.expires_in)), last_status="Authorized")
            self.global_status.setText("READY"); self.refresh()
        except Exception as exc: self.show_error(str(exc))

    def save_settings(self) -> None:
        key, secret, redirect = self.client_key.text().strip(), self.client_secret.text().strip(), self.redirect_uri.text().strip()
        if not all((key, secret, redirect)): self.show_error("All API settings are required"); return
        try:
            self.vault.set_app(key, secret, redirect); self.client_secret.clear(); QMessageBox.information(self, APP_NAME, "Saved to the OS keychain.")
        except Exception as exc: self.show_error(str(exc))

    def choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select video", "", "Videos (*.mp4 *.mov *.m4v *.webm)")
        if path: self.video.setText(path)

    def queue_post(self) -> None:
        account_id = self.account_combo.currentData()
        local = self.run_at.dateTime().toPython()
        if local.tzinfo is None: local = local.astimezone()
        try:
            self.registry.add_job(account_id, self.video.text(), self.caption.text(), local.astimezone(UTC), self.privacy.currentText())
            self.video.clear(); self.caption.clear(); self.refresh(); self.run_due()
        except Exception as exc: self.show_error(str(exc))

    def run_due(self) -> None:
        try:
            state = self.registry.snapshot(); now = utc_now()
            for job in state["jobs"]:
                if job["status"] != "queued" or parse_iso(job["run_at"]) > now or job["id"] in self.workers: continue
                try: claimed, account = self.registry.claim_job(job["id"])
                except StateError: continue
                worker = UploadThread(self.registry, self.vault, claimed, account); self.workers[job["id"]] = worker
                worker.progress_changed.connect(self.worker_progress); worker.succeeded.connect(self.worker_success); worker.failed.connect(self.worker_failed)
                worker.finished.connect(lambda job_id=job["id"]: self.worker_finished(job_id)); worker.start()
            if self.workers: self.global_status.setText(f"{len(self.workers)} ACTIVE")
        except Exception as exc:
            LOGGER.exception("Scheduler pass failed"); self.show_error(str(exc))

    def worker_progress(self, _: str, value: int, text: str) -> None:
        self.job_progress.setValue(value); self.global_status.setText(text.upper()[:28]); self.refresh()

    def worker_success(self, _: str, __: str, status: str) -> None:
        self.job_progress.setValue(100); self.global_status.setText(status.replace("_", " ")); self.refresh()

    def worker_failed(self, _: str, message: str) -> None:
        self.global_status.setText("ATTENTION"); self.show_error(message); self.refresh()

    def worker_finished(self, job_id: str) -> None:
        worker = self.workers.pop(job_id, None)
        if worker: worker.deleteLater()
        if not self.workers: self.global_status.setText("READY")
        self.refresh()

    def refresh(self) -> None:
        try: state = self.registry.snapshot()
        except Exception as exc: self.show_error(str(exc)); return
        selected_combo = self.account_combo.currentData() if hasattr(self, "account_combo") else None
        self.accounts.setRowCount(len(state["accounts"]))
        for row, account in enumerate(state["accounts"]):
            values = [account["name"], account["platform"], "Ready" if account.get("token_expires_at") else "Required",
                      account.get("last_post_at", "")[:19].replace("T", " ") or "Never", account.get("last_status", "")]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value));
                if col == 0: item.setData(Qt.UserRole, account["id"])
                self.accounts.setItem(row, col, item)
        self.account_combo.blockSignals(True); self.account_combo.clear()
        for account in state["accounts"]: self.account_combo.addItem(account["name"], account["id"])
        index = self.account_combo.findData(selected_combo)
        if index >= 0: self.account_combo.setCurrentIndex(index)
        self.account_combo.blockSignals(False)
        names = {a["id"]: a["name"] for a in state["accounts"]}; jobs = sorted(state["jobs"], key=lambda j: j["created_at"], reverse=True)
        self.jobs.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            values = [names.get(job["account_id"], "Removed"), Path(job["video_path"]).name,
                      job["run_at"][:19].replace("T", " "), job["status"], f"{job.get('progress', 0)}%",
                      job.get("server_status", ""), job.get("attempts", 0), job.get("last_error", "")]
            for col, value in enumerate(values): self.jobs.setItem(row, col, QTableWidgetItem(str(value)))

    def show_error(self, message: str) -> None:
        LOGGER.error("UI error: %s", message.replace("\n", " ")[:1000])
        QMessageBox.critical(self, APP_NAME, message)

    def closeEvent(self, event: Any) -> None:
        active = list(self.workers.values())
        for worker in active: worker.cancel()
        if self.oauth_worker: self.oauth_worker.cancel()
        deadline = time.monotonic() + 5
        for worker in active:
            worker.wait(max(0, int((deadline - time.monotonic()) * 1000)))
        event.accept()


def excepthook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
    LOGGER.critical("Unhandled exception", exc_info=(exc_type, exc, tb))


def main() -> int:
    sys.excepthook = excepthook
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME); app.setOrganizationName("SignalDesk"); app.setStyle("Fusion")
    font = QFont("Segoe UI", 10); app.setFont(font)
    window = MainWindow(); window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
