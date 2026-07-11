from __future__ import annotations

"""Test-first proxy assignment using the exact Guide + Profiller order."""

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
 QComboBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPlainTextEdit,
 QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import network_identity
import proxy_health

class ProxyTestWorker(QThread):
 row_result = Signal(int, object)
 completed = Signal()
 failed = Signal(str)

 def __init__(self, identities: list[network_identity.NetworkIdentity], parent=None):
  super().__init__(parent); self.identities = identities

 def run(self) -> None:
  try:
   for index, identity in enumerate(self.identities):
    self.row_result.emit(index, proxy_health.test(identity))
   self.completed.emit()
  except Exception as exc:
   self.failed.emit(str(exc))

def guide_profiles(window) -> list[str]:
 try:
  import publishing_flow_gui
  if hasattr(window, "guide_profiles_page"):
   return publishing_flow_gui.profiles(window)
 except Exception:
  pass
 return list(window.account_names()) if hasattr(window, "account_names") else []

def passing_identities(window) -> list[network_identity.NetworkIdentity]:
 return [
  window._tested_identities[index]
  for index, result in sorted(window._test_results.items())
  if result.ok and index < len(window._tested_identities)
 ]

def install(window_class) -> None:
 if getattr(window_class, "_network_identity_gui_installed", False): return
 original_build = window_class.build_ui; original_refresh = window_class.refresh

 def network_tab(self):
  page = QWidget(); layout = QVBoxLayout(page)
  title = QLabel("Proxy Testi ve Guide Profil Eşleştirme"); title.setStyleSheet("font-size: 20px; font-weight: 700")
  guide = QLabel(
   "Proxyleri test et. Testi geçenlerin tamamı Guide + Profiller sırasına atanır. "
   "Profil sayısından az proxy geçerse kalan profiller Atanmadı olarak bırakılır."
  )
  guide.setWordWrap(True); layout.addWidget(title); layout.addWidget(guide)
  scheme_row = QHBoxLayout(); scheme_row.addWidget(QLabel("Proxy tipi"))
  self.proxy_scheme = QComboBox(); self.proxy_scheme.addItems(["http", "https", "socks5"])
  self.proxy_scheme.currentTextChanged.connect(self.proxy_input_changed)
  scheme_row.addWidget(self.proxy_scheme); scheme_row.addStretch(); layout.addLayout(scheme_row)
  self.proxy_list_input = QPlainTextEdit(); self.proxy_list_input.setPlaceholderText(
   "socks5://kullanici:parola@host:port\nhost:port:kullanici:parola"
  )
  self.proxy_list_input.setMinimumHeight(150); self.proxy_list_input.textChanged.connect(self.proxy_input_changed)
  layout.addWidget(self.proxy_list_input)
  actions = QHBoxLayout(); self.proxy_test_button = QPushButton("1. PROXYLERİ TEST ET")
  self.proxy_test_button.clicked.connect(self.test_proxy_list)
  self.proxy_assign_button = QPushButton("2. TESTİ GEÇENLERİ GUIDE PROFİLLERİNE SIRAYLA ATA")
  self.proxy_assign_button.setObjectName("primaryButton"); self.proxy_assign_button.setEnabled(False)
  self.proxy_assign_button.clicked.connect(self.assign_proxy_list)
  clear = QPushButton("Tüm atamaları kaldır"); clear.clicked.connect(self.clear_all_proxy_assignments)
  for button in (self.proxy_test_button, self.proxy_assign_button, clear): actions.addWidget(button)
  actions.addStretch(); layout.addLayout(actions)
  self.proxy_mapping = QTableWidget(0, 6)
  self.proxy_mapping.setHorizontalHeaderLabels(["Sıra", "Guide profili", "Proxy", "Test", "Çıkış IP", "Detay"])
  header = self.proxy_mapping.horizontalHeader(); header.setSectionResizeMode(QHeaderView.ResizeToContents)
  header.setSectionResizeMode(1, QHeaderView.Stretch); header.setSectionResizeMode(2, QHeaderView.Stretch); header.setSectionResizeMode(5, QHeaderView.Stretch)
  layout.addWidget(self.proxy_mapping, 1)
  self.proxy_status = QLabel("Önce proxyleri test edin."); self.proxy_status.setWordWrap(True); layout.addWidget(self.proxy_status)
  self._tested_identities = []; self._test_results = {}; self._tested_source = ""; self.proxy_test_worker = None
  return page

 def proxy_source(self) -> str:
  return f"{self.proxy_scheme.currentText()}\n{self.proxy_list_input.toPlainText().strip()}"

 def proxy_input_changed(self, *_args) -> None:
  if hasattr(self, "proxy_assign_button") and self._tested_source != self.proxy_source():
   self.proxy_assign_button.setEnabled(False)
   if self._tested_source: self.proxy_status.setText("Proxy listesi değişti. Atamadan önce yeniden test edin.")

 def refresh_proxy_mapping(self) -> None:
  profiles = guide_profiles(self); tested = list(getattr(self, "_tested_identities", []))
  rows = max(len(profiles), len(tested)); self.proxy_mapping.setRowCount(rows)
  for row in range(rows):
   profile = profiles[row] if row < len(profiles) else ""; tested_identity = tested[row] if row < len(tested) else None
   saved = network_identity.load(profile) if profile else network_identity.NetworkIdentity()
   identity = tested_identity or saved; result = self._test_results.get(row)
   values = [str(row + 1), profile or "Profil yok", identity.server or "Atanmadı",
             "GEÇTİ" if result and result.ok else "BAŞARISIZ" if result else "Test bekliyor",
             result.exit_ip if result else "", result.detail if result else ""]
   for column, value in enumerate(values): self.proxy_mapping.setItem(row, column, QTableWidgetItem(value))

 def handle_proxy_result(self, index, result) -> None:
  self._test_results[index] = result; self.refresh_proxy_mapping()
  self.proxy_status.setText(f"Test sürüyor: {len(self._test_results)}/{len(self._tested_identities)}")

 def test_proxy_list(self) -> None:
  if self.proxy_test_worker and self.proxy_test_worker.isRunning(): return
  try:
   identities = network_identity.parse_proxy_list(self.proxy_list_input.toPlainText(), self.proxy_scheme.currentText())
   if not guide_profiles(self): raise RuntimeError("Guide + Profiller sekmesinde atanacak profil yok")
   self._tested_identities = identities; self._test_results = {}; self._tested_source = self.proxy_source()
   self.proxy_test_button.setEnabled(False); self.proxy_assign_button.setEnabled(False)
   self.proxy_status.setText("Proxyler test ediliyor..."); self.refresh_proxy_mapping()
   worker = ProxyTestWorker(identities, self); self.proxy_test_worker = worker
   worker.row_result.connect(self.handle_proxy_result); worker.completed.connect(self.proxy_test_finished)
   worker.failed.connect(self.proxy_test_failed); worker.finished.connect(lambda: self.proxy_test_button.setEnabled(True)); worker.start()
  except Exception as exc: QMessageBox.critical(self, "Proxy test hatası", str(exc))

 def proxy_test_finished(self) -> None:
  profiles = guide_profiles(self); passed = passing_identities(self)
  ready = bool(profiles and passed) and self._tested_source == self.proxy_source()
  self.proxy_assign_button.setEnabled(ready)
  assigned_count = min(len(passed), len(profiles)); remaining = len(profiles) - assigned_count
  message = f"Test bitti: {len(passed)}/{len(self._tested_identities)} geçti. {assigned_count} profile atamaya hazır."
  if remaining: message += f" Kalan {remaining} profil Atanmadı kalacak."
  if not passed: message = "Hiçbir proxy testi geçmedi; atanacak proxy yok."
  self.proxy_status.setText(message); self.refresh_proxy_mapping()

 def proxy_test_failed(self, detail: str) -> None:
  self.proxy_assign_button.setEnabled(False); self.proxy_status.setText(f"Proxy testi tamamlanamadı: {detail}")

 def assign_proxy_list(self) -> None:
  try:
   if self._tested_source != self.proxy_source(): raise RuntimeError("Liste testten sonra değişti. Yeniden test edin.")
   profiles = guide_profiles(self)
   if not profiles: raise RuntimeError("Guide + Profiller sekmesinde atanacak profil yok")
   passed = passing_identities(self)
   if not passed: raise RuntimeError("Testi geçen proxy yok")
   count = min(len(profiles), len(passed)); assigned_profiles = profiles[:count]
   assignments = network_identity.assign_in_order(assigned_profiles, passed[:count])
   for profile in profiles[count:]: network_identity.delete(profile)
   self._tested_identities = []; self._test_results = {}; self._tested_source = ""
   self.proxy_assign_button.setEnabled(False); self.refresh_proxy_mapping()
   import publishing_flow_gui
   if hasattr(self, "publish_profiles_table"):
    publishing_flow_gui.refresh_table(self); self.tabs.setCurrentWidget(self.guide_profiles_page)
    mapping = ", ".join(f"{profile}={identity.server}" for profile, identity in assignments)
    self.publish_status.setText(f"Proxy ataması hazır: {mapping}. {len(profiles) - count} profil Atanmadı.")
   self.proxy_status.setText(f"{count} geçen proxy Guide profillerine atandı; {len(profiles) - count} profil Atanmadı.")
   QMessageBox.information(self, "Proxy ataması tamamlandı", f"{count} geçen proxy atandı. {len(profiles) - count} profil Atanmadı kaldı.")
  except Exception as exc: QMessageBox.critical(self, "Proxy atama hatası", str(exc))

 def clear_all_proxy_assignments(self) -> None:
  for profile in guide_profiles(self): network_identity.delete(profile)
  self.refresh_proxy_mapping()
  try:
   import publishing_flow_gui
   if hasattr(self, "publish_profiles_table"): publishing_flow_gui.refresh_table(self)
  except Exception: pass
  self.proxy_status.setText("Guide profillerindeki tüm proxy atamaları kaldırıldı")

 def build_ui(self):
  original_build(self); self.network_identity_page = network_tab(self)
  self.tabs.addTab(self.network_identity_page, "Proxy Listesi"); self.refresh_proxy_mapping()

 def refresh(self):
  original_refresh(self)
  if hasattr(self, "proxy_mapping"): self.refresh_proxy_mapping()

 for name, value in {
  "network_tab": network_tab, "proxy_source": proxy_source, "proxy_input_changed": proxy_input_changed,
  "refresh_proxy_mapping": refresh_proxy_mapping, "handle_proxy_result": handle_proxy_result,
  "test_proxy_list": test_proxy_list, "proxy_test_finished": proxy_test_finished,
  "proxy_test_failed": proxy_test_failed, "assign_proxy_list": assign_proxy_list,
  "clear_all_proxy_assignments": clear_all_proxy_assignments, "build_ui": build_ui, "refresh": refresh,
 }.items(): setattr(window_class, name, value)
 window_class._network_identity_gui_installed = True
