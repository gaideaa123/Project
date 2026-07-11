from __future__ import annotations

"""Guide + profile assignment UI and ordered automatic web publishing."""

import inspect
import random
import re
import threading
from pathlib import Path
from typing import Any

import keyring
import requests
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import tiktok_login
import web_uploader

SERVICE = "signaldesk-azure-gpt4o"
DEFAULT_GUIDE = (
    "Konu: Videonun gerçek konusuna uygun Türkçe TikTok açıklaması.\n"
    "Ton: doğal, merak uyandıran, samimi ve güvenilir.\n"
    "Biçim: iki kısa cümle, 2-4 doğal emoji, ikinci satırda tam 5 alakalı hashtag.\n"
    "Doğrulanmamış sonuç, garanti, sahte deneyim veya abartılı vaat yazma."
)


def secret(name: str, default: str = "") -> str:
    try:
        return keyring.get_password(SERVICE, name) or default
    except Exception:
        return default


def save_secret(name: str, value: str) -> None:
    keyring.set_password(SERVICE, name, value)


def profiles(window: Any) -> list[str]:
    state = window.registry.snapshot()
    return [
        str(row.get("name") or row.get("profile_name") or "").strip()
        for row in state.get("accounts", [])
        if str(row.get("name") or row.get("profile_name") or "").strip()
    ]


class AzureCaptionClient:
    def __init__(self, key: str, url: str, guide: str):
        self.key = key.strip()
        self.url = url.strip()
        self.guide = guide.strip()
        if not self.key:
            raise RuntimeError("Azure GPT API anahtarı boş")
        if not self.url.startswith("https://") or "/chat/completions" not in self.url:
            raise RuntimeError("Azure chat/completions URL geçersiz")
        if not self.guide:
            raise RuntimeError("Guide boş")

    def create(self, profile: str) -> str:
        prompt = (
            "Türkçe TikTok captionu yaz, yalnız sonucu döndür.\n"
            f"Guide:\n{self.guide}\nProfil: {profile}\n"
            f"Çeşitlilik: {random.SystemRandom().randrange(10**12)}"
        )
        last_error = "Azure yanıt vermedi"
        for attempt in range(3):
            try:
                response = requests.post(
                    self.url,
                    headers={"api-key": self.key, "Content-Type": "application/json"},
                    json={
                        "temperature": 0.75 + attempt * 0.05,
                        "messages": [
                            {"role": "system", "content": "Kıdemli Türkçe sosyal medya editörüsün."},
                            {"role": "user", "content": prompt},
                        ],
                    },
                    timeout=(15, 90),
                )
                payload = response.json()
                if not response.ok:
                    error = payload.get("error", {})
                    detail = error.get("message") if isinstance(error, dict) else str(error)
                    raise RuntimeError(detail or f"HTTP {response.status_code}")
                caption = str(payload["choices"][0]["message"]["content"]).strip().strip('"')
                if not caption or len(caption) > 2200 or not re.search(r"\w", caption):
                    raise RuntimeError("Azure geçerli caption döndürmedi")
                return caption
            except Exception as exc:
                last_error = str(exc)
        raise RuntimeError(f"Azure caption üretemedi: {last_error}")


class PublishWorker(QThread):
    status = Signal(str)
    preview_ready = Signal(str, str, str)
    profile_done = Signal(str)
    all_done = Signal(int)
    failed = Signal(str)

    def __init__(self, assignments: list[tuple[str, Path]], key: str, url: str,
                 guide: str, parent=None):
        super().__init__(parent)
        self.assignments = assignments
        self.key, self.url, self.guide = key, url, guide
        self._decision = threading.Event()
        self._approved = False
        self._cancelled = False

    def decide(self, approved: bool) -> None:
        self._approved = approved
        self._decision.set()

    def cancel(self) -> None:
        self._cancelled = True
        self.decide(False)

    def approval(self, profile: str, video: Path, caption: str) -> bool:
        self._approved = False
        self._decision.clear()
        self.preview_ready.emit(profile, str(video), caption)
        self._decision.wait()
        return self._approved and not self._cancelled

    def run(self) -> None:
        completed = 0
        try:
            client = AzureCaptionClient(self.key, self.url, self.guide)
            signature = inspect.signature(web_uploader.prepare_upload)
            supports_publish = "publish" in signature.parameters
            for profile, video in self.assignments:
                if self._cancelled:
                    break
                if not video.is_file():
                    raise RuntimeError(f"Dağıtılan video bulunamadı: {video}")
                self.status.emit(f"{profile}: {video.name} için caption hazırlanıyor")
                caption = client.create(profile)
                request = web_uploader.UploadRequest(profile, video, caption)
                if supports_publish:
                    web_uploader.prepare_upload(
                        request,
                        publish=True,
                        approval=lambda p=profile, v=video, c=caption: self.approval(p, v, c),
                        status=self.status.emit,
                    )
                else:
                    self.status.emit(
                        f"{profile}: tarayıcı hazırlanıyor, son Yayınla onayı tarayıcıda"
                    )
                    web_uploader.prepare_upload(request)
                completed += 1
                self.profile_done.emit(profile)
            self.all_done.emit(completed)
        except Exception as exc:
            if self._cancelled or "iptal" in str(exc).casefold():
                self.all_done.emit(completed)
            else:
                self.failed.emit(str(exc))


def build_page(window: Any) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 18, 0, 0)
    layout.setSpacing(14)

    title = QLabel("Guide + Profiller")
    title.setObjectName("sectionTitle")
    note = QLabel(
        "Cold Open çıktıları hesap sırasına göre eşleşir: 1.mp4 ilk profile, "
        "2.mp4 ikinci profile. Üretim bitince otomatik yayın worker'ı başlar."
    )
    note.setObjectName("muted")
    note.setWordWrap(True)
    layout.addWidget(title)
    layout.addWidget(note)

    form = QFormLayout()
    window.publish_azure_key = QLineEdit(secret("api_key"))
    window.publish_azure_key.setEchoMode(QLineEdit.Password)
    window.publish_azure_url = QLineEdit(secret("api_url"))
    window.publish_guide = QPlainTextEdit(secret("guide", DEFAULT_GUIDE))
    window.publish_guide.setMinimumHeight(110)
    form.addRow("Azure API Key", window.publish_azure_key)
    form.addRow("Azure URL", window.publish_azure_url)
    form.addRow("Guide", window.publish_guide)
    layout.addLayout(form)

    controls = QHBoxLayout()
    save = QPushButton("Guide ve Azure ayarlarını kaydet")
    save.clicked.connect(lambda: save_settings(window, True))
    window.publish_auto_start = QCheckBox("Dağıtımdan sonra otomatik başlat")
    window.publish_auto_start.setChecked(secret("auto_start", "1") != "0")
    window.publish_start_button = QPushButton("DAĞITILAN VİDEOLARI YAYINLA")
    window.publish_start_button.setObjectName("primaryButton")
    window.publish_start_button.clicked.connect(lambda: start_publish(window))
    window.publish_cancel_button = QPushButton("İptal")
    window.publish_cancel_button.setEnabled(False)
    window.publish_cancel_button.clicked.connect(lambda: cancel_publish(window))
    controls.addWidget(save)
    controls.addWidget(window.publish_auto_start)
    controls.addWidget(window.publish_start_button)
    controls.addWidget(window.publish_cancel_button)
    controls.addStretch()
    layout.addLayout(controls)

    window.publish_profiles_table = QTableWidget(0, 5)
    window.publish_profiles_table.setHorizontalHeaderLabels(
        ["Sıra", "Profil", "Video", "Session ID", "Durum"]
    )
    header = window.publish_profiles_table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.Stretch)
    header.setSectionResizeMode(2, QHeaderView.Stretch)
    layout.addWidget(window.publish_profiles_table, 1)

    window.publish_status = QLabel("Cold Open çıktıları bekleniyor")
    window.publish_status.setObjectName("muted")
    window.publish_status.setWordWrap(True)
    layout.addWidget(window.publish_status)
    return page


def save_settings(window: Any, show_message: bool = False) -> bool:
    try:
        key = window.publish_azure_key.text().strip()
        url = window.publish_azure_url.text().strip()
        guide = window.publish_guide.toPlainText().strip()
        AzureCaptionClient(key, url, guide)
        save_secret("api_key", key)
        save_secret("api_url", url)
        save_secret("guide", guide)
        save_secret("auto_start", "1" if window.publish_auto_start.isChecked() else "0")
        if show_message:
            QMessageBox.information(window, "Kaydedildi", "Guide ve Azure ayarları kaydedildi.")
        return True
    except Exception as exc:
        if show_message:
            QMessageBox.critical(window, "Guide ayarı hatası", str(exc))
        return False


def refresh_table(window: Any) -> None:
    names = profiles(window)
    assigned = dict(getattr(window, "pending_assignments", []))
    table = window.publish_profiles_table
    table.clearContents()
    table.setRowCount(len(names))
    for row, name in enumerate(names):
        video = assigned.get(name)
        values = [
            str(row + 1),
            name,
            video.name if video else "Varyasyon bekliyor",
            "Kayıtlı" if tiktok_login.has_session(name) else "Eksik",
            "Atandı" if video else "Bekliyor",
        ]
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(value))


def distribute_outputs(window: Any, files: object) -> None:
    try:
        paths = [Path(value).resolve() for value in list(files or [])]
        if not paths or any(not path.is_file() for path in paths):
            raise RuntimeError("Uniquizer geçerli çıktı üretmedi")
        names = profiles(window)
        if not names:
            raise RuntimeError("Dağıtılacak profil yok; önce Session ID ile hesap ekleyin")
        if len(paths) < len(names):
            raise RuntimeError(
                f"{len(names)} profil var ama {len(paths)} varyasyon üretildi. "
                f"Varyasyon sayısını en az {len(names)} yapın."
            )
        window.pending_assignments = [
            (name, paths[index]) for index, name in enumerate(names)
        ]
        window.last_outputs = [str(path) for path in paths]
        refresh_table(window)
        window.tabs.setCurrentWidget(window.guide_profiles_page)
        mapping = ", ".join(
            f"{name}={video.name}" for name, video in window.pending_assignments
        )
        window.publish_status.setText(f"Dağıtım hazır: {mapping}")
        if window.publish_auto_start.isChecked():
            if save_settings(window, False):
                start_publish(window)
            else:
                window.publish_status.setText(
                    "Dağıtım hazır, otomatik yayın başlamadı: Azure Key, URL veya Guide eksik"
                )
                QMessageBox.warning(
                    window,
                    "Yayın ayarı eksik",
                    "Videolar profillere atandı. Guide + Profiller sekmesindeki "
                    "Azure Key, URL ve Guide alanlarını tamamlayın.",
                )
    except Exception as exc:
        QMessageBox.critical(window, "Dağıtım başarısız", str(exc))


def start_publish(window: Any) -> None:
    try:
        if getattr(window, "publish_worker", None) is not None:
            raise RuntimeError("Bir yayın akışı zaten çalışıyor")
        assignments = list(getattr(window, "pending_assignments", []))
        if not assignments:
            raise RuntimeError("Yayınlanacak dağıtım yok; önce Cold Open üretin")
        if not save_settings(window, False):
            raise RuntimeError("Azure Key, URL veya Guide geçersiz")
        worker = PublishWorker(
            assignments,
            window.publish_azure_key.text(),
            window.publish_azure_url.text(),
            window.publish_guide.toPlainText(),
            window,
        )
        window.publish_worker = worker
        worker.status.connect(window.publish_status.setText)
        worker.preview_ready.connect(lambda p, v, c: confirm_preview(window, p, v, c))
        worker.profile_done.connect(lambda p: mark_done(window, p))
        worker.failed.connect(lambda detail: publish_failed(window, detail))
        worker.all_done.connect(lambda count: publish_finished(window, count))
        worker.finished.connect(lambda: cleanup_worker(window))
        window.publish_start_button.setEnabled(False)
        window.publish_cancel_button.setEnabled(True)
        window.publish_status.setText("Otomatik yayın akışı başlatılıyor...")
        worker.start()
    except Exception as exc:
        window.publish_status.setText(f"Yayın başlatılamadı: {exc}")
        QMessageBox.critical(window, "Yayın başlatılamadı", str(exc))


def confirm_preview(window: Any, profile: str, video: str, caption: str) -> None:
    answer = QMessageBox.question(
        window,
        f"{profile}: son onay",
        f"Video: {Path(video).name}\n\nCaption:\n{caption}\n\nYayın akışı devam etsin mi?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if window.publish_worker:
        window.publish_worker.decide(answer == QMessageBox.Yes)


def mark_done(window: Any, profile: str) -> None:
    for row in range(window.publish_profiles_table.rowCount()):
        item = window.publish_profiles_table.item(row, 1)
        if item and item.text() == profile:
            window.publish_profiles_table.setItem(row, 4, QTableWidgetItem("Tamamlandı"))


def publish_failed(window: Any, detail: str) -> None:
    window.publish_status.setText(f"Başarısız: {detail}")
    QMessageBox.critical(window, "Yayın hatası", detail)


def publish_finished(window: Any, count: int) -> None:
    window.publish_status.setText(f"Yayın akışı tamamlandı: {count} profil")


def cancel_publish(window: Any) -> None:
    worker = getattr(window, "publish_worker", None)
    if worker:
        worker.cancel()
        window.publish_status.setText("Yayın akışı iptal ediliyor...")


def cleanup_worker(window: Any) -> None:
    worker = getattr(window, "publish_worker", None)
    window.publish_worker = None
    window.publish_start_button.setEnabled(True)
    window.publish_cancel_button.setEnabled(False)
    if worker:
        worker.deleteLater()


def install(window: Any) -> None:
    if getattr(window, "_publishing_flow_gui_installed", False):
        return
    window.pending_assignments = []
    window.publish_worker = None
    window.guide_profiles_page = build_page(window)
    session_index = window.tabs.indexOf(getattr(window, "session_accounts_page", None))
    insert_at = session_index + 1 if session_index >= 0 else 2
    window.tabs.insertTab(insert_at, window.guide_profiles_page, "Guide + Profiller")
    try:
        window.uniquizer_tab.outputs_ready.disconnect()
    except Exception:
        pass
    window.uniquizer_tab.outputs_ready.connect(lambda files: distribute_outputs(window, files))
    window._publishing_flow_gui_installed = True
    refresh_table(window)
