from __future__ import annotations

# This file is generated from the supported SignalDesk app_tr workflow.
# Network identity is installed as an additive UI tab; publishing behavior stays
# in the existing TurkceAnaPencere implementation.

import logging
import random
import re
import sys
import threading
from pathlib import Path

import keyring
import requests
from platformdirs import user_data_dir
from PySide6.QtCore import QLocale, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

import app as core
import network_identity_gui
import tiktok_login
import web_uploader
from uniquizer_tab import UniquizerTab

AZURE_SERVICE = "signaldesk-azure-gpt4o"
GUIDE = """Konu: Başlık üretmeyi kolaylaştıran faydalı bir internet sitesi.
Ton: doğal, merak uyandıran, enerjik, samimi ve güvenilir.
Biçim: iki kısa cümle, 2-4 doğal emoji, ikinci satırda tam 5 alakalı hashtag.
Dil: kusursuz Türkiye Türkçesi; anlatım, yazım ve noktalama hatası olmasın.
Doğrulanmamış sonuç, garanti, sahte deneyim veya abartılı vaat yazma."""
LOG_DIR = Path(user_data_dir("signaldesk-studio", "SignalDesk")); LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=LOG_DIR / "app_tr_errors.log", level=logging.INFO)
LOGGER = logging.getLogger("signaldesk.app_tr")
tiktok_login.install(web_uploader)


def secret(name, default=""):
    try: return keyring.get_password(AZURE_SERVICE, name) or default
    except Exception: return default


class AzureTitleClient:
    def __init__(self, key, url, guide):
        self.key, self.url, self.guide = key.strip(), url.strip(), guide.strip() or GUIDE
        if not self.key: raise RuntimeError("Azure GPT API anahtarı boş")
        if not self.url.startswith("https://") or "/chat/completions" not in self.url: raise RuntimeError("Azure URL geçersiz")

    def create(self, profile):
        prompt = f"Türkçe TikTok captionu yaz. Yalnız sonucu döndür.\nRehber: {self.guide}\nProfil: {profile}\nÇeşitlilik: {random.SystemRandom().randrange(10**12)}"
        last = "Azure yanıt vermedi"
        for attempt in range(3):
            try:
                response = requests.post(self.url, headers={"api-key": self.key, "Content-Type": "application/json"}, json={"temperature": .75 + attempt * .05, "messages": [{"role":"system","content":"Kıdemli Türkçe sosyal medya editörüsün."},{"role":"user","content":prompt}]}, timeout=(15,90))
                payload = response.json()
                if not response.ok: raise RuntimeError(str(payload.get("error", response.status_code)))
                caption = str(payload["choices"][0]["message"]["content"]).strip().strip('"')
                if caption and len(caption) <= 2200: return caption
            except Exception as exc: last = str(exc)
        raise RuntimeError(f"Azure caption üretemedi: {last}")


class PublishWorker(QThread):
    status = Signal(str); preview_ready = Signal(str, str, str); profile_done = Signal(str); all_done = Signal(int); failed = Signal(str)
    def __init__(self, assignments, key, url, guide, parent=None):
        super().__init__(parent); self.assignments=assignments; self.key=key; self.url=url; self.guide=guide; self._decision=threading.Event(); self._approved=False; self._cancelled=False
    def decide(self, approved): self._approved=approved; self._decision.set()
    def cancel(self): self._cancelled=True; self.decide(False)
    def _approval(self, profile, video, caption): self._approved=False; self._decision.clear(); self.preview_ready.emit(profile,str(video),caption); self._decision.wait(); return self._approved and not self._cancelled
    def run(self):
        completed=0
        try:
            client=AzureTitleClient(self.key,self.url,self.guide)
            for profile, video in self.assignments:
                if self._cancelled: break
                caption=client.create(profile)
                web_uploader.prepare_upload(web_uploader.UploadRequest(profile,video,caption),publish=True,approval=lambda p=profile,v=video,c=caption:self._approval(p,v,c),status=self.status.emit)
                completed+=1; self.profile_done.emit(profile)
            self.all_done.emit(completed)
        except Exception as exc:
            LOGGER.exception("Publish worker failed")
            if self._cancelled or "iptal" in str(exc).casefold(): self.all_done.emit(completed)
            else: self.failed.emit(str(exc))


class TurkceAnaPencere(core.MainWindow):
    def __init__(self): self.publish_worker=None; self.uniquizer_tab=None; self.pending_assignments=[]; super().__init__(); self.setWindowTitle("SignalDesk: Azure + Web Yayıncı")
    def build_ui(self):
        super().build_ui(); self.uniquizer_tab=UniquizerTab(self); self.uniquizer_tab.outputs_ready.connect(self.distribute_uniquizer_outputs); self.tabs.insertTab(1,self.uniquizer_tab,"Varyasyonlara Ayır"); self.azure_web_page=self.azure_web_tab(); self.tabs.insertTab(2,self.azure_web_page,"Azure + Web Yükleyici")
    def azure_web_tab(self):
        page=QWidget(); layout=QVBoxLayout(page); note=QLabel("1.mp4 ilk profile, 2.mp4 ikinci profile otomatik atanır."); layout.addWidget(note); form=QFormLayout(); self.azure_key=QLineEdit(secret("api_key")); self.azure_key.setEchoMode(QLineEdit.Password); self.azure_url=QLineEdit(secret("api_url")); self.azure_guide=QLineEdit(secret("guide",GUIDE)); form.addRow("Azure API Key",self.azure_key); form.addRow("Azure URL",self.azure_url); form.addRow("Guide",self.azure_guide); layout.addLayout(form); controls=QHBoxLayout(); add=QPushButton("SESSION ID İLE YENİ HESAP EKLE"); add.clicked.connect(self.add_session_account); publish=QPushButton("DAĞITILAN VİDEOLARI WEB İLE YAYINLA"); publish.clicked.connect(self.publish_distributed); self.cancel_publish=QPushButton("İptal"); self.cancel_publish.clicked.connect(self.cancel_current); [controls.addWidget(x) for x in (add,publish,self.cancel_publish)]; layout.addLayout(controls); self.web_profiles=QTableWidget(0,7); self.web_profiles.setHorizontalHeaderLabels(["Sıra","Profil","Video","Giriş","Session ID","Durum","İşlem"]); layout.addWidget(self.web_profiles); self.web_status=QLabel("Hazır"); layout.addWidget(self.web_status); return page
    def account_names(self): return [str(a.get("name") or a.get("profile_name") or "TikTok") for a in self.registry.snapshot().get("accounts",[])]
    def refresh(self): super().refresh(); self.refresh_web_profiles() if hasattr(self,"web_profiles") and self.publish_worker is None else None
    def refresh_web_profiles(self):
        names=self.account_names(); assigned=dict(self.pending_assignments); self.web_profiles.setRowCount(len(names))
        for row,name in enumerate(names):
            video=assigned.get(name); self.web_profiles.setItem(row,0,QTableWidgetItem(str(row+1))); self.web_profiles.setItem(row,1,QTableWidgetItem(name)); self.web_profiles.setItem(row,2,QTableWidgetItem(video.name if video else "Bekliyor")); self.web_profiles.setItem(row,5,QTableWidgetItem("Atandı" if video else "Bekliyor"))
    def distribute_uniquizer_outputs(self, files):
        paths=[Path(v).resolve() for v in list(files or [])]; names=self.account_names()
        if len(paths)<len(names): QMessageBox.critical(self,"Dağıtım başarısız","Profil sayısından az varyasyon var"); return
        self.pending_assignments=[(name,paths[i]) for i,name in enumerate(names)]; self.refresh_web_profiles(); self.start_publish(list(self.pending_assignments))
    def publish_distributed(self): self.start_publish(list(self.pending_assignments)) if self.pending_assignments else QMessageBox.warning(self,"Dağıtım yok","Önce varyasyon üretin")
    def start_publish(self, assignments):
        if self.publish_worker: return
        worker=PublishWorker(assignments,self.azure_key.text(),self.azure_url.text(),self.azure_guide.text(),self); self.publish_worker=worker; worker.status.connect(self.web_status.setText); worker.preview_ready.connect(self.confirm_preview); worker.failed.connect(self.publish_failed); worker.finished.connect(self.cleanup_worker); worker.start()
    def add_session_account(self):
        dialog=QDialog(self); layout=QFormLayout(dialog); profile=QLineEdit(); session=QLineEdit(); session.setEchoMode(QLineEdit.Password); layout.addRow("Profil",profile); layout.addRow("Session ID",session); buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addRow(buttons)
        if dialog.exec()!=QDialog.Accepted: return
        name=profile.text().strip()
        try: account=self.registry.add_account(name); tiktok_login.save_session(name,session.text()); self.refresh()
        except Exception as exc: QMessageBox.critical(self,"Hesap eklenemedi",str(exc))
    def confirm_preview(self, profile, video, caption):
        answer=QMessageBox.question(self,f"{profile}: son onay",f"{Path(video).name}\n\n{caption}\n\nYayınlansın mı?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No); self.publish_worker.decide(answer==QMessageBox.Yes) if self.publish_worker else None
    def cancel_current(self): self.publish_worker.cancel() if self.publish_worker else None
    def publish_failed(self, detail): self.web_status.setText("Başarısız"); QMessageBox.critical(self,"Yayın hatası",detail)
    def cleanup_worker(self): worker=self.publish_worker; self.publish_worker=None; worker.deleteLater() if worker else None


network_identity_gui.install(TurkceAnaPencere)


def main():
    app=QApplication(sys.argv); app.setStyle("Fusion"); QLocale.setDefault(QLocale(QLocale.Turkish,QLocale.Turkey)); window=TurkceAnaPencere(); window.show(); return app.exec()


if __name__=="__main__": raise SystemExit(main())
