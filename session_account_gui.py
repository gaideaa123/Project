from __future__ import annotations

"""Session ID / Cookie account management and publishing integration."""

import inspect
from typing import Any
from PySide6.QtWidgets import QCheckBox,QDialog,QDialogButtonBox,QFormLayout,QHBoxLayout,QLabel,QLineEdit,QMessageBox,QPushButton,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget
import auto_publish_flow,direct_connection_policy,tiktok_login
try:
 import web_uploader
 import published_review_bridge
 # Install order is deliberate: login first, automatic publisher second, then
 # the outermost outcome bridge so errors from every inner layer are classified.
 tiktok_login.install(web_uploader)
 auto_publish_flow.install(web_uploader)
 published_review_bridge.install(web_uploader)
except Exception:pass

def account_rows(window):
 rows=window.registry.snapshot().get("accounts",[]);return rows if isinstance(rows,list) else []
def account_name(account):return str(account.get("name") or account.get("profile_name") or "").strip()
def add_registry_account(window,name):
 method=window.registry.add_account;return method(name,"TikTok") if len(inspect.signature(method).parameters)>=2 else method(name)
def delete_registry_account(window,account_id):
 if account_id:window.registry.delete_account(account_id)
def session_page(window):
 page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(0,18,0,0);layout.setSpacing(14)
 title=QLabel("Session / Cookie ile TikTok Hesapları");title.setObjectName("sectionTitle")
 note=QLabel("Ham sessionid veya TikTok Cookie başlığını girin. En güvenilir giriş için sessionid, sessionid_ss ve varsa sid_guard/uid_tt içeren güncel Cookie başlığını kullanın.")
 note.setObjectName("muted");note.setWordWrap(True);layout.addWidget(title);layout.addWidget(note)
 actions=QHBoxLayout();window.session_add_button=QPushButton("SESSION / COOKIE İLE YENİ HESAP EKLE");window.session_add_button.setObjectName("primaryButton")
 window.session_add_button.clicked.connect(lambda:add_session_account(window));refresh=QPushButton("Listeyi yenile");refresh.clicked.connect(lambda:refresh_session_accounts(window))
 actions.addWidget(window.session_add_button);actions.addWidget(refresh);actions.addStretch();layout.addLayout(actions)
 window.session_accounts_table=QTableWidget(0,4);window.session_accounts_table.setHorizontalHeaderLabels(["Sıra","Profil","Session / Cookie","İşlem"]);window.session_accounts_table.horizontalHeader().setStretchLastSection(True);layout.addWidget(window.session_accounts_table,1)
 window.session_status=QLabel("Hazır");layout.addWidget(window.session_status);return page
def session_dialog(parent,title,profile=""):
 dialog=QDialog(parent);dialog.setWindowTitle(title);form=QFormLayout(dialog);profile_input=QLineEdit(profile);profile_input.setReadOnly(bool(profile))
 session_input=QLineEdit();session_input.setEchoMode(QLineEdit.Password);session_input.setPlaceholderText("sessionid değeri veya tam Cookie başlığı")
 show=QCheckBox("Session/Cookie bilgisini göster");show.toggled.connect(lambda checked:session_input.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password))
 form.addRow("Profil adı",profile_input);form.addRow("Session ID / Cookie",session_input);form.addRow("",show)
 buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
 return dialog.exec()==QDialog.Accepted,profile_input.text().strip(),session_input.text()
def add_session_account(window):
 accepted,name,raw=session_dialog(window,"Session / Cookie ile yeni TikTok hesabı")
 if not accepted:return
 account=None
 try:
  if not name:raise RuntimeError("Profil adı boş olamaz")
  tiktok_login._session_value(raw);account=add_registry_account(window,name)
  try:tiktok_login.save_session(name,raw)
  except Exception:delete_registry_account(window,str(account.get("id") or ""));raise
  if hasattr(window,"refresh"):window.refresh()
  refresh_session_accounts(window);window.session_status.setText(f"{name} session bilgisiyle eklendi")
 except Exception as exc:QMessageBox.critical(window,"Hesap eklenemedi",str(exc))
def edit_session(window,profile):
 accepted,_,raw=session_dialog(window,f"{profile}: Session / Cookie güncelle",profile)
 if not accepted:return
 try:tiktok_login.save_session(profile,raw);refresh_session_accounts(window)
 except Exception as exc:QMessageBox.critical(window,"Session bilgisi güncellenemedi",str(exc))
def remove_session(window,profile):
 if QMessageBox.question(window,"Session bilgisini kaldır",f"{profile} session bilgisi silinsin mi?",QMessageBox.Yes|QMessageBox.No)!=QMessageBox.Yes:return
 tiktok_login.delete_session(profile);refresh_session_accounts(window)
def refresh_session_accounts(window):
 if not hasattr(window,"session_accounts_table"):return
 rows=account_rows(window);window.session_accounts_table.setRowCount(len(rows))
 for row,account in enumerate(rows):
  profile=account_name(account);state="Kayıtlı" if tiktok_login.has_session(profile) else "Eksik"
  window.session_accounts_table.setItem(row,0,QTableWidgetItem(str(row+1)));window.session_accounts_table.setItem(row,1,QTableWidgetItem(profile));window.session_accounts_table.setItem(row,2,QTableWidgetItem(state))
def install(window):
 if getattr(window,"_session_account_gui_installed",False):return
 window.session_accounts_page=session_page(window);window.tabs.insertTab(1,window.session_accounts_page,"Session ID Hesapları");window._session_account_gui_installed=True;refresh_session_accounts(window)
 import publishing_flow_gui
 direct_connection_policy.install(publishing_flow_gui);publishing_flow_gui.install(window)
