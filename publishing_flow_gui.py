from __future__ import annotations

"""Guide, explicit profile order, existing-variant import, and proxy publishing."""

import inspect
import json
import random
import re
import threading
from pathlib import Path
from typing import Any

import keyring
import requests
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
 QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
 QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
 QTableWidgetItem, QVBoxLayout, QWidget,
)

import network_identity
import proxy_health
import tiktok_login
import web_uploader

SERVICE = "signaldesk-azure-gpt4o"
PROFILE_ORDER_KEY = "profile_order"
VARIANT_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
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

def registry_profiles(window: Any) -> list[str]:
 state = window.registry.snapshot()
 return [
  str(row.get("name") or row.get("profile_name") or "").strip()
  for row in state.get("accounts", [])
  if str(row.get("name") or row.get("profile_name") or "").strip()
 ]

def saved_profile_order(window: Any) -> list[str]:
 cached = getattr(window, "_publish_profile_order", None)
 if isinstance(cached, list):
  return list(cached)
 try:
  value = json.loads(secret(PROFILE_ORDER_KEY, "[]"))
  return [str(name) for name in value] if isinstance(value, list) else []
 except (TypeError, ValueError, json.JSONDecodeError):
  return []

def profiles(window: Any) -> list[str]:
 """Return current accounts in the user's persisted distribution order."""
 current = registry_profiles(window)
 saved = saved_profile_order(window)
 ordered = [name for name in saved if name in current]
 ordered.extend(name for name in current if name not in ordered)
 window._publish_profile_order = ordered
 return list(ordered)

def save_profile_order(window: Any, names: list[str]) -> None:
 current = registry_profiles(window)
 if set(names) != set(current) or len(names) != len(current):
  raise RuntimeError("Profil sırası güncel hesap listesiyle eşleşmiyor")
 window._publish_profile_order = list(names)
 save_secret(PROFILE_ORDER_KEY, json.dumps(names, ensure_ascii=False))

def validated_proxy(profile: str) -> network_identity.NetworkIdentity:
 identity = network_identity.load(profile)
 if not identity.server:
  raise RuntimeError(
   f"{profile}: proxy atanmadı. Önce Proxy Listesi sekmesinde proxyleri test edip sırayla atayın."
  )
 try:
  proxy_health.require_healthy(identity)
 except Exception as exc:
  raise RuntimeError(f"{profile}: atanmış proxy sağlıklı değil: {exc}") from exc
 return identity

def validate_proxy_assignments(names: list[str]) -> dict[str, network_identity.NetworkIdentity]:
 if not names:
  raise RuntimeError("Proxy doğrulanacak profil yok")
 return {name: validated_proxy(name) for name in names}

def numbered_variants(folder: Path) -> list[Path]:
 """Load 1.mp4, 2.mp4... in numeric order, never lexicographic order."""
 folder = folder.expanduser().resolve()
 if not folder.is_dir():
  raise RuntimeError("Geçerli bir uniquize çıktı klasörü seçin")
 indexed: dict[int, Path] = {}
 for path in folder.iterdir():
  if not path.is_file() or path.suffix.casefold() not in VARIANT_EXTENSIONS:
   continue
  if not path.stem.isdigit():
   continue
  index = int(path.stem)
  if index < 1:
   continue
  if index in indexed:
   raise RuntimeError(f"Aynı sıra numarası iki kez var: {index}")
  indexed[index] = path.resolve()
 if not indexed:
  raise RuntimeError("Klasörde 1.mp4, 2.mp4 şeklinde numaralı varyasyon bulunamadı")
 expected = list(range(1, max(indexed) + 1))
 missing = [str(index) for index in expected if index not in indexed]
 if missing:
  raise RuntimeError("Varyasyon sırası eksik: " + ", ".join(missing))
 return [indexed[index] for index in expected]

class AzureCaptionClient:
 def __init__(self, key: str, url: str, guide: str):
  self.key = key.strip(); self.url = url.strip(); self.guide = guide.strip()
  if not self.key: raise RuntimeError("Azure GPT API anahtarı boş")
  if not self.url.startswith("https://") or "/chat/completions" not in self.url:
   raise RuntimeError("Azure chat/completions URL geçersiz")
  if not self.guide: raise RuntimeError("Guide boş")

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
     json={"temperature": 0.75 + attempt * 0.05, "messages": [
      {"role": "system", "content": "Kıdemli Türkçe sosyal medya editörüsün."},
      {"role": "user", "content": prompt},
     ]},
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
 status = Signal(str); preview_ready = Signal(str, str, str)
 profile_done = Signal(str); all_done = Signal(int); failed = Signal(str)

 def __init__(self, assignments: list[tuple[str, Path]], key: str, url: str, guide: str, parent=None):
  super().__init__(parent); self.assignments = assignments
  self.key, self.url, self.guide = key, url, guide
  self._decision = threading.Event(); self._approved = False; self._cancelled = False

 def decide(self, approved: bool) -> None:
  self._approved = approved; self._decision.set()

 def cancel(self) -> None:
  self._cancelled = True; self.decide(False)

 def approval(self, profile: str, video: Path, caption: str) -> bool:
  self._approved = False; self._decision.clear()
  self.preview_ready.emit(profile, str(video), caption); self._decision.wait()
  return self._approved and not self._cancelled

 def run(self) -> None:
  completed = 0
  try:
   client = AzureCaptionClient(self.key, self.url, self.guide)
   supports_publish = "publish" in inspect.signature(web_uploader.prepare_upload).parameters
   for profile, video in self.assignments:
    if self._cancelled: break
    if not video.is_file(): raise RuntimeError(f"Dağıtılan video bulunamadı: {video}")
    identity = validated_proxy(profile)
    self.status.emit(f"{profile}: {video.name}, proxy {identity.server} ile caption hazırlanıyor")
    caption = client.create(profile)
    request = web_uploader.UploadRequest(profile, video, caption)
    if supports_publish:
     web_uploader.prepare_upload(
      request, publish=True,
      approval=lambda p=profile, v=video, c=caption: self.approval(p, v, c),
      status=self.status.emit,
     )
    else:
     self.status.emit(f"{profile}: atanmış proxy ile tarayıcı hazırlanıyor")
     web_uploader.prepare_upload(request)
    completed += 1; self.profile_done.emit(profile)
   self.all_done.emit(completed)
  except Exception as exc:
   if self._cancelled or "iptal" in str(exc).casefold(): self.all_done.emit(completed)
   else: self.failed.emit(str(exc))

def build_page(window: Any) -> QWidget:
 page = QWidget(); layout = QVBoxLayout(page)
 layout.setContentsMargins(0, 18, 0, 0); layout.setSpacing(14)
 title = QLabel("Guide + Profiller"); title.setObjectName("sectionTitle")
 note = QLabel(
  "Dağıtım sırasını oklarla ayarla. Yeni üretim yapabilir veya daha önce uniquize "
  "edilmiş 1.mp4, 2.mp4... klasörünü doğrudan dağıtabilirsin."
 )
 note.setObjectName("muted"); note.setWordWrap(True)
 layout.addWidget(title); layout.addWidget(note)

 form = QFormLayout()
 window.publish_azure_key = QLineEdit(secret("api_key")); window.publish_azure_key.setEchoMode(QLineEdit.Password)
 window.publish_azure_url = QLineEdit(secret("api_url"))
 window.publish_guide = QPlainTextEdit(secret("guide", DEFAULT_GUIDE)); window.publish_guide.setMinimumHeight(110)
 form.addRow("Azure API Key", window.publish_azure_key)
 form.addRow("Azure URL", window.publish_azure_url)
 form.addRow("Guide", window.publish_guide)
 layout.addLayout(form)

 existing_row = QHBoxLayout()
 window.existing_variants_folder = QLineEdit(); window.existing_variants_folder.setReadOnly(True)
 window.existing_variants_folder.setPlaceholderText("Önceden uniquize edilmiş 1.mp4, 2.mp4... klasörü")
 choose_existing = QPushButton("Klasör seç")
 choose_existing.clicked.connect(lambda: choose_existing_folder(window))
 window.distribute_existing_button = QPushButton("ÖNCEDEN UNIQUIZE EDİLMİŞ VİDEOLARI DAĞIT")
 window.distribute_existing_button.setObjectName("primaryButton")
 window.distribute_existing_button.clicked.connect(lambda: distribute_existing_variants(window))
 existing_row.addWidget(window.existing_variants_folder, 1)
 existing_row.addWidget(choose_existing)
 existing_row.addWidget(window.distribute_existing_button)
 layout.addLayout(existing_row)

 controls = QHBoxLayout(); save = QPushButton("Guide ve Azure ayarlarını kaydet")
 save.clicked.connect(lambda: save_settings(window, True))
 window.publish_auto_start = QCheckBox("Proxy doğrulandıktan sonra otomatik başlat")
 window.publish_auto_start.setChecked(secret("auto_start", "1") != "0")
 window.publish_start_button = QPushButton("PROXYLİ DAĞITIMI YAYINLA"); window.publish_start_button.setObjectName("primaryButton")
 window.publish_start_button.clicked.connect(lambda: start_publish(window))
 window.publish_cancel_button = QPushButton("İptal"); window.publish_cancel_button.setEnabled(False)
 window.publish_cancel_button.clicked.connect(lambda: cancel_publish(window))
 for widget in (save, window.publish_auto_start, window.publish_start_button, window.publish_cancel_button): controls.addWidget(widget)
 controls.addStretch(); layout.addLayout(controls)

 window.publish_profiles_table = QTableWidget(0, 7)
 window.publish_profiles_table.setHorizontalHeaderLabels(
  ["Sıra", "Profil", "Video", "Proxy", "Session ID", "Durum", "Sırayı değiştir"]
 )
 header = window.publish_profiles_table.horizontalHeader(); header.setSectionResizeMode(QHeaderView.ResizeToContents)
 header.setSectionResizeMode(1, QHeaderView.Stretch); header.setSectionResizeMode(2, QHeaderView.Stretch); header.setSectionResizeMode(3, QHeaderView.Stretch)
 layout.addWidget(window.publish_profiles_table, 1)
 window.publish_status = QLabel("Önce Proxy Listesi'nde proxyleri test edip atayın")
 window.publish_status.setObjectName("muted"); window.publish_status.setWordWrap(True); layout.addWidget(window.publish_status)
 return page

def save_settings(window: Any, show_message: bool = False) -> bool:
 try:
  key = window.publish_azure_key.text().strip(); url = window.publish_azure_url.text().strip(); guide = window.publish_guide.toPlainText().strip()
  AzureCaptionClient(key, url, guide)
  save_secret("api_key", key); save_secret("api_url", url); save_secret("guide", guide)
  save_secret("auto_start", "1" if window.publish_auto_start.isChecked() else "0")
  if show_message: QMessageBox.information(window, "Kaydedildi", "Guide ve Azure ayarları kaydedildi.")
  return True
 except Exception as exc:
  if show_message: QMessageBox.critical(window, "Guide ayarı hatası", str(exc))
  return False

def choose_existing_folder(window: Any) -> None:
 initial = window.existing_variants_folder.text().strip() or str(Path.home())
 folder = QFileDialog.getExistingDirectory(window, "Uniquize edilmiş video klasörünü seç", initial)
 if folder:
  window.existing_variants_folder.setText(str(Path(folder).resolve()))
  try:
   files = numbered_variants(Path(folder))
   window.publish_status.setText(f"{len(files)} numaralı varyasyon bulundu. Dağıtmaya hazır.")
  except Exception as exc:
   window.publish_status.setText(f"Klasör kullanılamıyor: {exc}")

def distribute_existing_variants(window: Any) -> None:
 try:
  folder_text = window.existing_variants_folder.text().strip()
  if not folder_text:
   raise RuntimeError("Önce uniquize edilmiş videoların klasörünü seçin")
  files = numbered_variants(Path(folder_text))
  distribute_outputs(window, files)
 except Exception as exc:
  window.publish_status.setText(f"Hazır varyasyonlar dağıtılamadı: {exc}")
  QMessageBox.critical(window, "Hazır varyasyon dağıtımı başarısız", str(exc))

def move_profile(window: Any, profile: str, direction: int) -> None:
 try:
  worker = getattr(window, "publish_worker", None)
  if worker is not None:
   raise RuntimeError("Yayın çalışırken profil sırası değiştirilemez")
  names = profiles(window)
  index = names.index(profile); target = index + direction
  if target < 0 or target >= len(names):
   return
  names[index], names[target] = names[target], names[index]
  save_profile_order(window, names)
  assignments = list(getattr(window, "pending_assignments", []))
  if assignments:
   videos = [video for _, video in assignments]
   window.pending_assignments = list(zip(names, videos, strict=False))
  refresh_table(window)
  window.publish_status.setText("Dağıtım sırası güncellendi: " + " → ".join(names))
 except Exception as exc:
  QMessageBox.critical(window, "Sıra değiştirilemedi", str(exc))

def refresh_table(window: Any) -> None:
 names = profiles(window); assigned = dict(getattr(window, "pending_assignments", [])); table = window.publish_profiles_table
 table.clearContents(); table.setRowCount(len(names))
 for row, name in enumerate(names):
  video = assigned.get(name); identity = network_identity.load(name)
  proxy_text = identity.server if identity.server else "ATANMADI"
  state = "Atandı" if video and identity.server else "Proxy bekliyor" if video else "Bekliyor"
  values = [str(row + 1), name, video.name if video else "Varyasyon bekliyor", proxy_text,
            "Kayıtlı" if tiktok_login.has_session(name) else "Eksik", state]
  for column, value in enumerate(values): table.setItem(row, column, QTableWidgetItem(value))
  actions = QWidget(); action_layout = QHBoxLayout(actions); action_layout.setContentsMargins(0, 0, 0, 0)
  up = QPushButton("Yukarı"); down = QPushButton("Aşağı")
  up.setEnabled(row > 0); down.setEnabled(row < len(names) - 1)
  up.clicked.connect(lambda _=False, profile=name: move_profile(window, profile, -1))
  down.clicked.connect(lambda _=False, profile=name: move_profile(window, profile, 1))
  action_layout.addWidget(up); action_layout.addWidget(down)
  table.setCellWidget(row, 6, actions)

def distribute_outputs(window: Any, files: object) -> None:
 try:
  paths = [Path(value).resolve() for value in list(files or [])]
  if not paths or any(not path.is_file() for path in paths): raise RuntimeError("Uniquizer geçerli çıktı üretmedi")
  names = profiles(window)
  if not names: raise RuntimeError("Dağıtılacak profil yok; önce Session ID ile hesap ekleyin")
  if len(paths) < len(names):
   raise RuntimeError(f"{len(names)} profil var ama {len(paths)} varyasyon üretildi. Varyasyon sayısını en az {len(names)} yapın.")
  identities = validate_proxy_assignments(names)
  window.pending_assignments = [(name, paths[index]) for index, name in enumerate(names)]
  window.last_outputs = [str(path) for path in paths]
  refresh_table(window); window.tabs.setCurrentWidget(window.guide_profiles_page)
  mapping = ", ".join(f"{name}={video.name}@{identities[name].server}" for name, video in window.pending_assignments)
  window.publish_status.setText(f"Proxyli dağıtım hazır: {mapping}")
  if window.publish_auto_start.isChecked():
   if save_settings(window, False): start_publish(window)
   else:
    window.publish_status.setText("Proxyli dağıtım hazır, otomatik yayın başlamadı: Azure Key, URL veya Guide eksik")
    QMessageBox.warning(window, "Yayın ayarı eksik", "Proxy ve videolar eşleşti. Guide + Profiller sekmesindeki Azure alanlarını tamamlayın.")
 except Exception as exc:
  if hasattr(window, "guide_profiles_page"): window.tabs.setCurrentWidget(window.guide_profiles_page)
  if hasattr(window, "publish_status"): window.publish_status.setText(f"Dağıtım engellendi: {exc}")
  QMessageBox.critical(window, "Proxyli dağıtım başarısız", str(exc))

def start_publish(window: Any) -> None:
 try:
  if getattr(window, "publish_worker", None) is not None: raise RuntimeError("Bir yayın akışı zaten çalışıyor")
  assignments = list(getattr(window, "pending_assignments", []))
  if not assignments: raise RuntimeError("Yayınlanacak dağıtım yok; önce Cold Open üretin veya hazır varyasyon klasörü seçin")
  validate_proxy_assignments([name for name, _ in assignments])
  if not save_settings(window, False): raise RuntimeError("Azure Key, URL veya Guide geçersiz")
  worker = PublishWorker(assignments, window.publish_azure_key.text(), window.publish_azure_url.text(), window.publish_guide.toPlainText(), window)
  window.publish_worker = worker; worker.status.connect(window.publish_status.setText)
  worker.preview_ready.connect(lambda p, v, c: confirm_preview(window, p, v, c))
  worker.profile_done.connect(lambda p: mark_done(window, p)); worker.failed.connect(lambda detail: publish_failed(window, detail))
  worker.all_done.connect(lambda count: publish_finished(window, count)); worker.finished.connect(lambda: cleanup_worker(window))
  window.publish_start_button.setEnabled(False); window.distribute_existing_button.setEnabled(False)
  window.publish_cancel_button.setEnabled(True); window.publish_status.setText("Atanmış proxylerle otomatik yayın akışı başlatılıyor...")
  worker.start()
 except Exception as exc:
  window.publish_status.setText(f"Yayın başlatılamadı: {exc}"); QMessageBox.critical(window, "Yayın başlatılamadı", str(exc))

def confirm_preview(window: Any, profile: str, video: str, caption: str) -> None:
 identity = network_identity.load(profile)
 answer = QMessageBox.question(
  window, f"{profile}: son onay",
  f"Profil: {profile}\nVideo: {Path(video).name}\nProxy: {identity.server}\n\nCaption:\n{caption}\n\nYayın akışı devam etsin mi?",
  QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
 )
 if window.publish_worker: window.publish_worker.decide(answer == QMessageBox.Yes)

def mark_done(window: Any, profile: str) -> None:
 for row in range(window.publish_profiles_table.rowCount()):
  item = window.publish_profiles_table.item(row, 1)
  if item and item.text() == profile: window.publish_profiles_table.setItem(row, 5, QTableWidgetItem("Tamamlandı"))

def publish_failed(window: Any, detail: str) -> None:
 window.publish_status.setText(f"Başarısız: {detail}"); QMessageBox.critical(window, "Yayın hatası", detail)

def publish_finished(window: Any, count: int) -> None:
 window.publish_status.setText(f"Proxyli yayın akışı tamamlandı: {count} profil")

def cancel_publish(window: Any) -> None:
 worker = getattr(window, "publish_worker", None)
 if worker: worker.cancel(); window.publish_status.setText("Yayın akışı iptal ediliyor...")

def cleanup_worker(window: Any) -> None:
 worker = getattr(window, "publish_worker", None); window.publish_worker = None
 window.publish_start_button.setEnabled(True); window.distribute_existing_button.setEnabled(True)
 window.publish_cancel_button.setEnabled(False)
 if worker: worker.deleteLater()

def install(window: Any) -> None:
 if getattr(window, "_publishing_flow_gui_installed", False): return
 window.pending_assignments = []; window.publish_worker = None; window._publish_profile_order = None
 window.guide_profiles_page = build_page(window)
 session_index = window.tabs.indexOf(getattr(window, "session_accounts_page", None)); insert_at = session_index + 1 if session_index >= 0 else 2
 window.tabs.insertTab(insert_at, window.guide_profiles_page, "Guide + Profiller")
 try: window.uniquizer_tab.outputs_ready.disconnect()
 except Exception: pass
 window.uniquizer_tab.outputs_ready.connect(lambda files: distribute_outputs(window, files))
 window._publishing_flow_gui_installed = True; refresh_table(window)
