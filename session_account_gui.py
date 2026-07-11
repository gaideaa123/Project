from __future__ import annotations

"""Session ID account management and publishing integration."""

import inspect
from typing import Any

from PySide6.QtWidgets import (
 QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
 QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
 QVBoxLayout, QWidget,
)

import auto_publish_flow
import direct_connection_policy
import tiktok_login

try:
 import web_uploader
 tiktok_login.install(web_uploader)
 auto_publish_flow.install(web_uploader)
except Exception:
 pass

def account_rows(window: Any) -> list[dict[str, Any]]:
 state=window.registry.snapshot(); rows=state.get("accounts",[]); return rows if isinstance(rows,list) else []
def account_name(account: dict[str, Any]) -> str: return str(account.get("name") or account.get("profile_name") or "").strip()
def add_registry_account(window: Any,name: str) -> dict[str,Any]:
 method=window.registry.add_account; parameter_count=len(inspect.signature(method).parameters)
 return method(name,"TikTok") if parameter_count>=2 else method(name)
def delete_registry_account(window: Any,account_id: str) -> None:
 if account_id: window.registry.delete_account(account_id)

def session_page(window: Any) -> QWidget:
 page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(0,18,0,0); layout.setSpacing(14)
 title=QLabel("Session ID ile TikTok Hesapları"); title.setObjectName("sectionTitle")
 note=QLabel("Profil adı ve sessionid girin. Session ID yalnız işletim sistemi güvenli kasasında tutulur; tabloda veya proje dosyalarında gösterilmez.")
 note.setObjectName("muted"); note.setWordWrap(True); layout.addWidget(title); layout.addWidget(note)
 actions=QHBoxLayout(); window.session_add_button=QPushButton("SESSION ID İLE YENİ HESAP EKLE"); window.session_add_button.setObjectName("primaryButton")
 window.session_add_button.clicked.connect(lambda:add_session_account(window)); refresh_button=QPushButton("Listeyi yenile"); refresh_button.clicked.connect(lambda:refresh_session_accounts(window))
 actions.addWidget(window.session_add_button); actions.addWidget(refresh_button); actions.addStretch(); layout.addLayout(actions)
 window.session_accounts_table=QTableWidget(0,4); window.session_accounts_table.setHorizontalHeaderLabels(["Sıra","Profil","Session ID","İşlem"])
 window.session_accounts_table.horizontalHeader().setStretchLastSection(True); layout.addWidget(window.session_accounts_table,1)
 window.session_status=QLabel("Hazır"); layout.addWidget(window.session_status); return page

def session_dialog(parent:Any,title:str,profile:str="") -> tuple[bool,str,str]:
 dialog=QDialog(parent); dialog.setWindowTitle(title); form=QFormLayout(dialog); profile_input=QLineEdit(profile); profile_input.setReadOnly(bool(profile))
 session_input=QLineEdit(); session_input.setEchoMode(QLineEdit.Password); show=QCheckBox("Session ID'yi göster")
 show.toggled.connect(lambda checked:session_input.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password))
 form.addRow("Profil adı",profile_input); form.addRow("Session ID",session_input); form.addRow("",show)
 buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
 return dialog.exec()==QDialog.Accepted,profile_input.text().strip(),session_input.text()

def add_session_account(window:Any) -> None:
 accepted,name,raw_session=session_dialog(window,"Session ID ile yeni TikTok hesabı")
 if not accepted:return
 account=None
 try:
  if not name:raise RuntimeError("Profil adı boş olamaz")
  tiktok_login._session_value(raw_session); account=add_registry_account(window,name)
  try:tiktok_login.save_session(name,raw_session)
  except Exception:delete_registry_account(window,str(account.get("id") or "")); raise
  if hasattr(window,"refresh"):window.refresh()
  refresh_session_accounts(window); window.session_status.setText(f"{name} Session ID ile eklendi")
 except Exception as exc:QMessageBox.critical(window,"Hesap eklenemedi",str(exc))

def edit_session(window:Any,profile:str) -> None:
 accepted,_,raw_session=session_dialog(window,f"{profile}: Session ID güncelle",profile)
 if not accepted:return
 try:tiktok_login.save_session(profile,raw_session); refresh_session_accounts(window)
 except Exception as exc:QMessageBox.critical(window,"Session ID güncellenemedi",str(exc))
def remove_session(window:Any,profile:str) -> None:
 if QMessageBox.question(window,"Session ID'yi kaldır",f"{profile} Session ID silinsin mi?",QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:return
 tiktok_login.delete_session(profile); refresh_session_accounts(window)

def refresh_session_accounts(window:Any) -> None:
 if not hasattr(window,"session_accounts_table"):return
 rows=account_rows(window); window.session_accounts_table.setRowCount(len(rows))
 for row,account in enumerate(rows):
  profile=account_name(account); state="Kayıtlı" if tiktok_login.has_session(profile) else "Eksik"
  window.session_accounts_table.setItem(row,0,QTableWidgetItem(str(row+1))); window.session_accounts_table.setItem(row,1,QTableWidgetItem(profile)); window.session_accounts_table.setItem(row,2,QTableWidgetItem(state))

def install(window:Any) -> None:
 if getattr(window,"_session_account_gui_installed",False):return
 window.session_accounts_page=session_page(window); window.tabs.insertTab(1,window.session_accounts_page,"Session ID Hesapları")
 window._session_account_gui_installed=True; refresh_session_accounts(window)
 import publishing_flow_gui
 direct_connection_policy.install(publishing_flow_gui)
 publishing_flow_gui.install(window)
