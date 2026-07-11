from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import keyring
from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
 QApplication, QCheckBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
 QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

import app as core
import network_identity_gui
import publishing_flow_gui
import qa_runtime_dependencies
from proxy_publisher import install_proxy_backend
from uniquizer_tab import UniquizerTab

AYAR_SERVISI = "signaldesk-agency-console.app-settings"
VARSAYILAN_REDIRECT = "http://127.0.0.1:3455/callback/"
VARSAYILAN_KAPSAMLAR = "user.info.basic,video.publish"

METINLER = {
 "SIGNALDESK / AGENCY OPERATIONS": "SIGNALDESK / AJANS OPERASYONLARI",
 "SIGNALDESK / PUBLISH OPERATIONS": "SIGNALDESK / AJANS OPERASYONLARI",
 "Ship content with a paper trail.": "İçeriği kayıtlı, kontrollü ve güvenli yayınla.",
 "Content control, without the chaos.": "İçeriği kayıtlı, kontrollü ve güvenli yayınla.",
 "Profile Manager": "Profil Yönetimi", "Accounts": "Profil Yönetimi", "Profiles": "Profil Yönetimi",
 "Batch Processing": "Toplu Medya İşleme", "Processing": "Toplu Medya İşleme", "Asset processing": "Toplu Medya İşleme",
 "Deployment Queue": "Yayın Kuyruğu", "Deployment queue": "Yayın Kuyruğu", "Scheduler": "Yayın Kuyruğu",
 "Connect an official channel": "Resmî bir kanal bağla", "Connect a profile": "Resmî bir kanal bağla",
 "Profile": "Profil", "Profile name": "Profil", "Platform": "Platform", "Access token": "Erişim belirteci",
 "Refresh token": "Yenileme belirteci", "Network gateway": "Ağ geçidi", "Network proxy": "Ağ geçidi",
 "Add profile": "Profil ekle", "Authorized profiles": "Yetkilendirilmiş profiller", "Connected profiles": "Yetkilendirilmiş profiller",
 "Remove selected": "Seçileni kaldır", "Token": "Belirteç", "Token health": "Belirteç", "Network": "Ağ", "Added": "Eklenme",
 "H.264 rendition batch": "H.264 çıktı paketi", "Delivery renditions": "H.264 çıktı paketi", "Select master": "Ana dosyayı seç",
 "Choose video": "Ana dosyayı seç", "Select folder": "Çıktı klasörünü seç", "Start batch": "Toplu işlemi başlat",
 "Render outputs": "Toplu işlemi başlat", "Processing log": "İşlem günlüğü", "Live operations log": "İşlem günlüğü", "Browse": "Gözat",
 "Deployment time": "Yayın zamanı", "Run at": "Yayın zamanı", "Caption": "Açıklama", "Repeat daily": "Her gün tekrarla",
 "Queue deployment": "Yayını kuyruğa ekle", "Queue post": "Yayını kuyruğa ekle", "23-hour guarded pipeline": "23 saat korumalı yayın hattı",
 "Posting pipeline": "23 saat korumalı yayın hattı", "Run due jobs": "Zamanı gelenleri çalıştır", "Run due now": "Zamanı gelenleri çalıştır",
 "Asset": "Medya", "Video": "Medya", "Next run": "Sonraki çalışma", "Next deployment": "Sonraki çalışma",
 "Cadence": "Tekrar", "State": "Durum", "Publish ID": "Yayın kimliği",
}
DURUM = {"Ready":"Hazır","Refresh soon":"Yakında yenilenecek","Gateway":"Ağ geçidi","Approved proxy":"Ağ geçidi","Direct":"Doğrudan","Daily":"Günlük","Once":"Tek sefer","Queued":"Kuyrukta","Running":"Çalışıyor","Failed":"Başarısız","Submitted":"Gönderildi"}

def kasa_oku(ad: str, varsayilan: str = "") -> str:
 try: return keyring.get_password(AYAR_SERVISI, ad) or varsayilan
 except Exception: return varsayilan

def ayarlari_yukle() -> None:
 values={"TIKTOK_CLIENT_KEY":kasa_oku("client_key"),"TIKTOK_CLIENT_SECRET":kasa_oku("client_secret"),"TIKTOK_REDIRECT_URI":kasa_oku("redirect_uri",VARSAYILAN_REDIRECT),"TIKTOK_SCOPES":kasa_oku("scopes",VARSAYILAN_KAPSAMLAR)}
 for name,value in values.items():
  if value: os.environ[name]=value

class TurkceAnaPencere(core.MainWindow):
 def __init__(self) -> None:
  self.uniquizer_tab=None; super().__init__(); install_proxy_backend(self); publishing_flow_gui.install(self)
 def build_ui(self) -> None:
  super().build_ui(); self.setWindowTitle("SignalDesk Ajans Paneli"); self._cekirdek_uyumlulugunu_kur()
  self.uniquizer_tab=UniquizerTab(self); self.uniquizer_tab.outputs_ready.connect(self._uniquizer_outputs_ready); self.tabs.insertTab(1,self.uniquizer_tab,"Cold Open Uniquizer")
  self.api_page=self.api_sekmesi(); self.tabs.addTab(self.api_page,"API Ayarları"); self._cevir()
 def _cekirdek_uyumlulugunu_kur(self) -> None:
  if not hasattr(self,"master") and hasattr(self,"master_video"):self.master=self.master_video
  if not hasattr(self,"batch_size") and hasattr(self,"variant_count"):self.batch_size=self.variant_count
  if not hasattr(self,"progress") and hasattr(self,"render_progress"):self.progress=self.render_progress
  if not hasattr(self,"output_dir"):
   self.output_dir=QLineEdit(); self.output_dir.setPlaceholderText("Çıktı klasörünü seçin veya tam yolu yazın"); self.output_dir.setClearButtonEnabled(True)
   button=QPushButton("Çıktı klasörünü seç"); button.clicked.connect(self.choose_output); row=QHBoxLayout(); row.addWidget(self.output_dir,1); row.addWidget(button)
   processing_page=self.tabs.widget(1); page_layout=processing_page.layout() if processing_page else None; controls=None
   if page_layout:
    for index in range(page_layout.count()):
     widget=page_layout.itemAt(index).widget()
     if isinstance(widget,QFrame) and widget.layout():controls=widget;break
   if controls and controls.layout():controls.layout().insertLayout(max(0,controls.layout().count()-3),row)
   elif page_layout:page_layout.addLayout(row)
  self.output_dir.setReadOnly(False); self.output_dir.setClearButtonEnabled(True); self.output_dir.editingFinished.connect(self._normalize_output)
 def _uniquizer_outputs_ready(self,files:object)->None:
  outputs=[str(Path(value).resolve()) for value in list(files or [])]
  if not outputs:QMessageBox.critical(self,"Cold Open Uniquizer","Uniquizer geçerli çıktı üretmedi.");return
  self.last_outputs=outputs; queue_field=getattr(self,"queue_video",getattr(self,"schedule_video",None))
  if queue_field is not None:queue_field.setText(outputs[0])
  if hasattr(self,"log"):self.log(f"Cold Open Uniquizer: {len(outputs)} çıktı hazır")
 def api_sekmesi(self)->QWidget:
  page=QWidget();outer=QHBoxLayout(page);outer.setContentsMargins(0,18,0,0);panel=QFrame();panel.setObjectName("panel");layout=QVBoxLayout(panel);layout.setContentsMargins(28,24,28,28);layout.setSpacing(16)
  title=QLabel("TikTok API ve OAuth Ayarları");title.setObjectName("sectionTitle");note=QLabel("Uygulama anahtarları güvenli kasada, profil belirteçleri Profil Yönetimi'nde saklanır.");note.setObjectName("muted");note.setWordWrap(True);layout.addWidget(title);layout.addWidget(note)
  form=QFormLayout();self.client_key_alani=QLineEdit(kasa_oku("client_key"));self.client_secret_alani=QLineEdit(kasa_oku("client_secret"));self.client_secret_alani.setEchoMode(QLineEdit.Password);self.redirect_alani=QLineEdit(kasa_oku("redirect_uri",VARSAYILAN_REDIRECT));self.kapsam_alani=QLineEdit(kasa_oku("scopes",VARSAYILAN_KAPSAMLAR))
  for label,widget in (("Client Key",self.client_key_alani),("Client Secret",self.client_secret_alani),("Redirect URI",self.redirect_alani),("OAuth kapsamları",self.kapsam_alani)):form.addRow(label,widget)
  layout.addLayout(form);buttons=QHBoxLayout();save=QPushButton("Ayarları güvenli kasaya kaydet");save.setObjectName("primaryButton");save.clicked.connect(self.api_kaydet);auth=QPushButton("Profil belirteçlerini al");auth.clicked.connect(self.oauth_ac);show=QCheckBox("Client Secret'ı göster");show.toggled.connect(lambda checked:self.client_secret_alani.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password))
  for widget in (save,auth,show):buttons.addWidget(widget)
  buttons.addStretch();layout.addLayout(buttons);layout.addStretch();outer.addWidget(panel,1);return page
 def api_kaydet(self,bilgi_goster:bool=True)->bool:
  data={"client_key":self.client_key_alani.text().strip(),"client_secret":self.client_secret_alani.text().strip(),"redirect_uri":self.redirect_alani.text().strip(),"scopes":self.kapsam_alani.text().strip()}
  if not all(data.values()):QMessageBox.warning(self,"Eksik API ayarı","Tüm API alanlarını doldurun.");return False
  try:
   for name,value in data.items():keyring.set_password(AYAR_SERVISI,name,value)
   ayarlari_yukle();
   if bilgi_goster:QMessageBox.information(self,"Kaydedildi","API ayarları güvenli kasaya kaydedildi.")
   return True
  except Exception as exc:self.error("API ayarları kaydedilemedi",str(exc));return False
 def oauth_ac(self)->None:
  if not self.api_kaydet(False):return
  helper=Path(__file__).with_name("oauth_helper.py")
  try:
   kwargs={"cwd":str(helper.parent),"env":os.environ.copy()}
   if sys.platform=="win32":kwargs["creationflags"]=subprocess.CREATE_NEW_CONSOLE
   subprocess.Popen([sys.executable,str(helper)],**kwargs)
  except Exception as exc:self.error("OAuth yardımcısı açılamadı",str(exc))
 def _cevir(self)->None:
  for index in range(self.tabs.count()):self.tabs.setTabText(index,METINLER.get(self.tabs.tabText(index),self.tabs.tabText(index)))
  for label in self.findChildren(QLabel):label.setText(METINLER.get(label.text(),label.text()))
  for button in self.findChildren(QPushButton):button.setText(METINLER.get(button.text(),button.text()))
 def refresh(self)->None:
  if hasattr(super(),"refresh"):super().refresh()
  elif hasattr(super(),"refresh_all"):super().refresh_all()
  self._cevir()
  if hasattr(self,"publish_profiles_table"):publishing_flow_gui.refresh_table(self)
 def _normalize_output(self)->None:
  if self.output_dir.text().strip():self.output_dir.setText(str(Path(self.output_dir.text().strip()).expanduser().resolve()))
 def choose_output(self)->None:
  selected=QFileDialog.getExistingDirectory(self,"Çıktı klasörünü seç",self.output_dir.text().strip() or str(Path.home()))
  if selected:self.output_dir.setText(str(Path(selected).resolve()))
 def choose_master(self)->None:
  path,_=QFileDialog.getOpenFileName(self,"Ana medya dosyasını seç","","Medya (*.mp4 *.mov *.mkv *.webm)")
  if path:self.master.setText(str(Path(path).resolve()))
 def start_batch(self)->None:self.error("Bilgi","Toplu medya motoru çekirdek tarafından yönetiliyor.")
 def _batch_done(self,outputs:object)->None:self.last_outputs=list(outputs or [])
 def start_render(self)->None:self.start_batch()
 def error(self,title:str,details:str)->None:
  if hasattr(super(),"error"):super().error(title,details)
  else:super().show_error(title,details)
 def closeEvent(self,event)->None:
  if self.uniquizer_tab is not None and not self.uniquizer_tab.shutdown(5000):event.ignore();return
  worker=getattr(self,"publish_worker",None)
  if worker is not None and worker.isRunning():worker.cancel();worker.wait(5000)
  super().closeEvent(event)

network_identity_gui.install(TurkceAnaPencere)

def main()->int:
 try:
  qa_runtime_dependencies.ensure_dependencies()
 except qa_runtime_dependencies.DependencyBootstrapError as exc:
  print(f"HATA: {exc}",file=sys.stderr);return 1
 ayarlari_yukle();app=QApplication(sys.argv);app.setApplicationName("SignalDesk Ajans Paneli");app.setOrganizationName("SignalDesk");app.setStyle("Fusion");QLocale.setDefault(QLocale(QLocale.Turkish,QLocale.Turkey));window=TurkceAnaPencere();window.show();return app.exec()

if __name__=="__main__":raise SystemExit(main())
