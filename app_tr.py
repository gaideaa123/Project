from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import ffmpeg
import keyring
import requests
from PySide6.QtCore import QLocale, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import app as core

TIKTOK_SERVICE = "signaldesk-agency-console.app-settings"
AZURE_SERVICE = "signaldesk-azure-gpt4o"
AZURE_DEFAULT_URL = "https://yedekhesap145566-4746-resource.cognitiveservices.azure.com/openai/deployments/gpt-4o/chat/completions?api-version=2025-01-01-preview"
REDIRECT = "http://127.0.0.1:3455/callback/"
SCOPES = "user.info.basic,video.publish"
DEFAULT_OUTPUT = Path(r"C:\Users\ahmet\Music\cikti")
HISTORY_FILE = core.DATA_DIR / "azure_caption_history.json"
GUIDE = """Konu: Başlık üretmeyi kolaylaştıran faydalı bir internet sitesi.
Ton: doğal, merak uyandıran, enerjik, samimi ve güvenilir.
Biçim: iki kısa cümle, 2-4 doğal emoji, ikinci satırda tam 5 alakalı hashtag.
Dil: kusursuz Türkiye Türkçesi; anlatım, yazım ve noktalama hatası olmasın.
Doğrulanmamış sonuç, garanti, sahte deneyim veya abartılı vaat yazma."""


def get_secret(service: str, name: str, default: str = "") -> str:
    try: return keyring.get_password(service, name) or default
    except Exception: return default


def load_settings() -> None:
    values = {
        "TIKTOK_CLIENT_KEY": get_secret(TIKTOK_SERVICE, "client_key"),
        "TIKTOK_CLIENT_SECRET": get_secret(TIKTOK_SERVICE, "client_secret"),
        "TIKTOK_REDIRECT_URI": get_secret(TIKTOK_SERVICE, "redirect_uri", REDIRECT),
        "TIKTOK_SCOPES": get_secret(TIKTOK_SERVICE, "scopes", SCOPES),
    }
    for name, value in values.items():
        if value: os.environ[name] = value


def norm(text: str) -> str: return re.sub(r"\s+", " ", text.casefold()).strip(" \"'")
def load_history() -> list[str]:
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8")); return data if isinstance(data, list) else []
    except Exception: return []
def save_history(items: list[str]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True); tmp = HISTORY_FILE.with_suffix(".tmp"); tmp.write_text(json.dumps(items[-1000:], ensure_ascii=False, indent=2), encoding="utf-8"); os.replace(tmp, HISTORY_FILE)


class AzureCaptionClient:
    def __init__(self, key: str, url: str, guide: str):
        self.key, self.url, self.guide = key.strip(), url.strip(), guide.strip() or GUIDE
        if not self.key: raise RuntimeError("Azure GPT-4o API anahtarı boş")
        if not self.url.startswith("https://") or "/chat/completions" not in self.url: raise RuntimeError("Azure GPT-4o API URL geçersiz")
    def create(self, profile: str, history: list[str]) -> str:
        known = {norm(x) for x in history}
        prompt = f"""Türkçe TikTok captionu yaz. Yalnız sonucu döndür.
Rehber: {self.guide}
İlk satır iki kısa doğal cümle ve 2-4 emoji içersin. İkinci satır yalnız tam 5 hashtag olsun.
Dil bilgisi kusursuz olsun. Geçmiştekileri kopyalama veya yakın kalıp kullanma.
Profil: {profile}
Geçmiş: {json.dumps(history[-100:], ensure_ascii=False)}"""
        for attempt in range(5):
            response = requests.post(self.url, headers={"api-key": self.key, "Content-Type": "application/json"}, json={"temperature": 0.75 + attempt * .05, "messages": [{"role": "system", "content": "Kıdemli Türkçe sosyal medya editörüsün."}, {"role": "user", "content": prompt + f"\nÇeşitlilik: {random.randrange(10**12)}"}]}, timeout=(15, 90))
            try: data = response.json()
            except ValueError as exc: raise RuntimeError(f"Azure GPT-4o geçersiz JSON döndürdü: HTTP {response.status_code}") from exc
            if not response.ok:
                error = data.get("error", {}); detail = error.get("message") if isinstance(error, dict) else str(error); raise RuntimeError(f"Azure GPT-4o API hatası: {detail or response.status_code}")
            caption = str(data["choices"][0]["message"]["content"]).strip().strip('"')
            lines = [x.strip() for x in caption.splitlines() if x.strip()]
            tags = re.findall(r"(?<!\w)#[\wçğıöşüÇĞİÖŞÜ]+", lines[1]) if len(lines) == 2 else []
            if len(lines) == 2 and len(tags) == 5 and norm(caption) not in known:
                history.append(caption); save_history(history); return caption
        raise RuntimeError("Azure GPT-4o kurallara uyan benzersiz caption üretemedi")


def probe(path: Path) -> tuple[float, bool]:
    data = ffmpeg.probe(str(path)); duration = float(data.get("format", {}).get("duration") or 0); audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    if duration <= 0: raise RuntimeError("Video süresi okunamadı")
    return duration, audio


def chain(label: str, speed: float, zoom: float, teaser: bool) -> str:
    pts = "PTS-STARTPTS" if teaser else f"(PTS-STARTPTS)/{speed:.6f}"
    return f"[{label}:v]setpts={pts},scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,scale=iw*{zoom:.6f}:ih*{zoom:.6f}:flags=lanczos,crop=1080:1920,fps=30,settb=AVTB,setsar=1,format=yuv420p"


def render_video(source: Path, count: int, progress, status) -> list[str]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"): raise RuntimeError("FFmpeg ve FFprobe PATH üzerinde bulunamadı")
    duration, audio = probe(source); DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True); rng = random.SystemRandom(); outputs = []
    for i in range(count):
        speed, zoom = rng.uniform(.992, 1.012), rng.uniform(1.006, 1.025); teaser_len = min(rng.uniform(.75, 1.2), max(.35, duration * .15)); teaser_at = min(duration * rng.choice((.28, .42, .58, .7)), max(0, duration - teaser_len - .2)); target = DEFAULT_OUTPUT / f"{i+1}.mp4"
        filters = [f"{chain('0', 1, zoom+.012, True)}[tv]", f"{chain('1', speed, zoom, False)}[mv]", "[tv][mv]concat=n=2:v=1:a=0[outv]"]
        if audio: filters += ["[0:a]asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[ta]", f"[1:a]asetpts=PTS-STARTPTS,atempo={speed:.6f},aresample=48000:async=1:first_pts=0,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[ma]", "[ta][ma]concat=n=2:v=0:a=1[outa]"]
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{teaser_at:.3f}", "-t", f"{teaser_len:.3f}", "-i", str(source), "-i", str(source), "-filter_complex", ";".join(filters), "-map", "[outv]"]
        if audio: cmd += ["-map", "[outa]"]
        cmd += ["-c:v", "libx264", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30"]
        if audio: cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
        cmd += ["-movflags", "+faststart", "-map_metadata", "-1", "-shortest", str(target)]; status(f"{i+1}/{count}: {target.name}"); result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode: target.unlink(missing_ok=True); raise RuntimeError(result.stderr.strip())
        outputs.append(str(target)); progress(round((i+1)*100/count))
    return outputs


class RenderWorker(QThread):
    progress=Signal(int); status=Signal(str); done=Signal(object); failed=Signal(str)
    def __init__(self, source, count, parent=None): super().__init__(parent); self.source=source; self.count=count
    def run(self):
        try: self.done.emit(render_video(self.source,self.count,self.progress.emit,self.status.emit))
        except Exception as exc: self.failed.emit(str(exc))


class PublishWorker(QThread):
    status=Signal(str); done=Signal(int); failed=Signal(str)
    def __init__(self, registry, assignments, key, url, guide, parent=None): super().__init__(parent); self.registry=registry; self.assignments=assignments; self.key=key; self.url=url; self.guide=guide
    def run(self):
        try:
            history=load_history(); client=AzureCaptionClient(self.key,self.url,self.guide)
            for i,(account,video) in enumerate(self.assignments,1):
                self.status.emit(f"{account.get('name','Profil')}: Azure GPT-4o caption yazıyor"); caption=client.create(account.get('name','TikTok'),history)
                # TikTok resmi kuralı: audit edilmemiş Direct Post istemcisi yalnız SELF_ONLY kullanabilir.
                self.registry.add_job(account["id"],str(video),caption,core.utc_now(),"SELF_ONLY")
                self.status.emit(f"{i}/{len(self.assignments)} gizli test yayını kuyruğa eklendi")
            self.done.emit(len(self.assignments))
        except Exception as exc: self.failed.emit(str(exc))


class TurkceAnaPencere(core.MainWindow):
    def build_ui(self):
        super().build_ui(); self.setWindowTitle("SignalDesk Azure GPT-4o Yayıncı"); self.render_worker=None; self.publish_worker=None
        self.tabs.insertTab(1,self.video_tab(),"Tek Tık Video"); self.tabs.insertTab(2,self.profiles_tab(),"Profiller + Azure GPT-4o"); self.tabs.addTab(self.api_tab(),"API Ayarları")
    def video_tab(self):
        page=QWidget(); layout=QVBoxLayout(page); form=QFormLayout(); self.master=QLineEdit(); choose=QPushButton("Input seç"); choose.clicked.connect(self.choose); row=QHBoxLayout(); row.addWidget(self.master); row.addWidget(choose); form.addRow("Input",row); self.count=QSpinBox(); self.count.setRange(1,100); self.count.setValue(5); form.addRow("Adet",self.count); form.addRow("Output",QLabel(str(DEFAULT_OUTPUT))); layout.addLayout(form); self.render_btn=QPushButton("VARYANTLARI OLUŞTUR"); self.render_btn.clicked.connect(self.render); layout.addWidget(self.render_btn); self.progress=QProgressBar(); layout.addWidget(self.progress); self.render_status=QLabel("Hazır"); layout.addWidget(self.render_status); layout.addStretch(); return page
    def profiles_tab(self):
        page=QWidget(); layout=QVBoxLayout(page); warning=QLabel("TikTok audit tamamlanana kadar API yayınları yalnızca gizli (SELF_ONLY) gönderilir. Audit sonrası herkese açık seçenek açılabilir."); warning.setWordWrap(True); layout.addWidget(warning); bar=QHBoxLayout(); all_btn=QPushButton("Hepsini seç"); all_btn.clicked.connect(self.select_all); pub=QPushButton("SEÇİLENLERE CAPTION ÜRET VE GİZLİ TEST YAYINI YAP"); pub.clicked.connect(self.publish_selected); bar.addWidget(all_btn); bar.addWidget(pub); layout.addLayout(bar); self.table=QTableWidget(0,4); self.table.setHorizontalHeaderLabels(["Seç","Profil","Video","İşlem"]); self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch); layout.addWidget(self.table); self.publish_status=QLabel("Hazır"); layout.addWidget(self.publish_status); self.refresh_profiles(); return page
    def api_tab(self):
        page=QWidget(); layout=QVBoxLayout(page); form=QFormLayout(); self.azure_key=QLineEdit(get_secret(AZURE_SERVICE,"api_key")); self.azure_key.setEchoMode(QLineEdit.Password); self.azure_url=QLineEdit(get_secret(AZURE_SERVICE,"api_url",AZURE_DEFAULT_URL)); form.addRow("Azure GPT-4o API Key",self.azure_key); form.addRow("Azure GPT-4o API URL",self.azure_url); layout.addLayout(form); self.guide=QPlainTextEdit(get_secret(AZURE_SERVICE,"guide",GUIDE)); layout.addWidget(self.guide); save=QPushButton("AZURE AYARLARINI KAYDET"); save.clicked.connect(self.save_azure); layout.addWidget(save); return page
    def refresh_profiles(self):
        accounts=self.registry.snapshot().get("accounts",[]); self.table.setRowCount(len(accounts))
        for row,account in enumerate(accounts):
            self.table.setCellWidget(row,0,QCheckBox()); self.table.setItem(row,1,QTableWidgetItem(account.get("name","TikTok"))); self.table.setItem(row,2,QTableWidgetItem(f"{row+1}.mp4")); btn=QPushButton("Caption üretip gizli yükle"); btn.clicked.connect(lambda _=False,r=row:self.publish_rows([r])); self.table.setCellWidget(row,3,btn)
    def select_all(self):
        for row in range(self.table.rowCount()): self.table.cellWidget(row,0).setChecked(True)
    def publish_selected(self): self.publish_rows([r for r in range(self.table.rowCount()) if self.table.cellWidget(r,0).isChecked()])
    def publish_rows(self,rows):
        accounts=self.registry.snapshot().get("accounts",[]); assignments=[(accounts[r],DEFAULT_OUTPUT/f"{r+1}.mp4") for r in rows if r<len(accounts)]
        if not assignments: QMessageBox.warning(self,"Profil yok","En az bir profil seçin"); return
        missing=[str(v) for _,v in assignments if not v.is_file()]
        if missing: QMessageBox.warning(self,"Video eksik","\n".join(missing)); return
        self.save_azure(False); self.publish_worker=PublishWorker(self.registry,assignments,self.azure_key.text(),self.azure_url.text(),self.guide.toPlainText(),self); self.publish_worker.status.connect(self.publish_status.setText); self.publish_worker.done.connect(self.published); self.publish_worker.failed.connect(lambda m:QMessageBox.critical(self,"Yayın hatası",m)); self.publish_worker.start()
    def published(self,count): self.publish_status.setText(f"{count} gizli yayın kuyruğa alındı"); QTimer.singleShot(100,self.run_due)
    def choose(self):
        path,_=QFileDialog.getOpenFileName(self,"Video seç","","Video (*.mp4 *.mov *.mkv *.webm *.m4v)");
        if path:self.master.setText(path)
    def render(self):
        source=Path(self.master.text().strip())
        if not source.is_file(): QMessageBox.warning(self,"Video yok","Geçerli video seçin"); return
        self.render_btn.setEnabled(False); self.render_worker=RenderWorker(source,self.count.value(),self); self.render_worker.progress.connect(self.progress.setValue); self.render_worker.status.connect(self.render_status.setText); self.render_worker.done.connect(lambda o:(setattr(self,"last_outputs",list(o or [])),self.refresh_profiles())); self.render_worker.failed.connect(lambda m:QMessageBox.critical(self,"FFmpeg hatası",m)); self.render_worker.finished.connect(lambda:self.render_btn.setEnabled(True)); self.render_worker.start()
    def save_azure(self,notify=True):
        if not self.azure_key.text().strip() or not self.azure_url.text().strip():
            if notify: QMessageBox.warning(self,"Eksik Azure ayarı","API key ve URL girin")
            return
        keyring.set_password(AZURE_SERVICE,"api_key",self.azure_key.text().strip()); keyring.set_password(AZURE_SERVICE,"api_url",self.azure_url.text().strip()); keyring.set_password(AZURE_SERVICE,"guide",self.guide.toPlainText().strip())
        if notify: QMessageBox.information(self,"Kaydedildi","Azure ayarları kaydedildi")


def main():
    load_settings(); qt=QApplication(sys.argv); qt.setStyle("Fusion"); QLocale.setDefault(QLocale(QLocale.Turkish,QLocale.Turkey)); window=TurkceAnaPencere(); window.show(); return qt.exec()
if __name__=="__main__": raise SystemExit(main())
