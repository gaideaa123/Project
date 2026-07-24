from __future__ import annotations
"""
CaptionAI TikTok Studio
-----------------------
Accounts tab   : add/remove TikTok profiles, OAuth 2.0 PKCE via browser
Upload tab     : pick video, Groq auto-generates English caption, upload
API Keys tab   : TikTok Client Key/Secret + Groq key, OS keychain only

pip install PySide6 requests keyring platformdirs
"""
import contextlib, hashlib, json, logging, os, secrets, string, sys
import tempfile, threading, time, urllib.parse, uuid, webbrowser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable

import keyring, requests
from platformdirs import user_data_dir
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

APP_NAME     = "CaptionAI TikTok Studio"
APP_SLUG     = "captionai-tiktok-studio"
UTC          = timezone.utc
TIKTOK_API   = "https://open.tiktokapis.com"
TIKTOK_AUTH  = "https://www.tiktok.com/v2/auth/authorize/"
KEYRING_SVC  = "captionai-tiktok-studio"
REDIRECT_URI = "http://127.0.0.1:3455/callback/"


def utc_now(): return datetime.now(UTC)
def iso(dt): return dt.astimezone(UTC).isoformat()
def parse_iso(s):
    p = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return p if p.tzinfo else p.replace(tzinfo=UTC)
def data_dir():
    p = Path(user_data_dir(APP_SLUG, "CaptionAI")); p.mkdir(parents=True, exist_ok=True); return p

DATA_DIR = data_dir()

def _build_logger():
    log = logging.getLogger(APP_SLUG); log.setLevel(logging.INFO); log.propagate = False
    if not log.handlers:
        h = RotatingFileHandler(DATA_DIR / "studio.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(threadName)s | %(message)s"))
        log.addHandler(h)
    return log

LOGGER = _build_logger()


class AppError(RuntimeError): pass
class ApiError(AppError): pass
class Cancelled(AppError): pass


class Vault:
    def _w(self, k, v): keyring.set_password(KEYRING_SVC, k, v)
    def _r(self, k): return keyring.get_password(KEYRING_SVC, k) or ""
    def set_app(self, ck, cs): self._w("app:ck", ck); self._w("app:cs", cs)
    def app(self): return self._r("app:ck"), self._r("app:cs")
    def set_groq(self, k): self._w("groq:key", k)
    def groq(self): return self._r("groq:key")
    def set_tokens(self, uid, a, r): self._w(f"{uid}:a", a); self._w(f"{uid}:r", r)
    def tokens(self, uid): return self._r(f"{uid}:a"), self._r(f"{uid}:r")
    def del_tokens(self, uid):
        for s in ("a","r"):
            with contextlib.suppress(Exception): keyring.delete_password(KEYRING_SVC, f"{uid}:{s}")


class Registry:
    def __init__(self, path):
        self.path = path; self._lock = threading.RLock()
        if not path.exists(): self._write({"accounts": []})
    def _read(self):
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(d.get("accounts"), list): return d
        except Exception: pass
        return {"accounts": []}
    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="cai-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, self.path)
        finally:
            with contextlib.suppress(OSError): os.unlink(tmp)
    def snapshot(self):
        with self._lock: return json.loads(json.dumps(self._read()))
    def _mutate(self, fn):
        with self._lock: s = self._read(); r = fn(s); self._write(s); return r
    def add_account(self, name):
        name = name.strip()
        if not name: raise AppError("Profile name cannot be empty")
        acc = {"id": uuid.uuid4().hex, "name": name, "platform": "TikTok",
               "created_at": iso(utc_now()), "token_expires_at": "", "last_status": "No token"}
        def fn(s):
            if any(a["name"].casefold() == name.casefold() for a in s["accounts"]):
                raise AppError("A profile with that name already exists")
            s["accounts"].append(acc); return acc
        return self._mutate(fn)
    def update_account(self, uid, **kw):
        def fn(s):
            a = next((x for x in s["accounts"] if x["id"] == uid), None)
            if a: a.update(kw)
        self._mutate(fn)
    def remove_account(self, uid):
        self._mutate(lambda s: s.__setitem__("accounts", [a for a in s["accounts"] if a["id"] != uid]))


def _http():
    retry = Retry(total=4, backoff_factor=0.6, status_forcelist=(429,500,502,503,504),
                  allowed_methods=frozenset({"GET","POST","PUT"}), raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    s = requests.Session(); s.headers.update({"User-Agent": f"{APP_NAME}/1.0"})
    s.mount("https://", adapter); s.mount("http://", adapter); return s

HTTP = _http()


def _tt(resp):
    try:
        data = resp.json()
    except ValueError as e:
        raise ApiError(f"Non-JSON response from TikTok (HTTP {resp.status_code}): {resp.text[:300]}") from e
    
    err = data.get("error") or {}
    code = err.get("code")
    msg = err.get("message", "")
    log_id = err.get("log_id", "")
    
    if not resp.ok or (code not in (None, "", "ok", 0, "0")):
        detail = f"TikTok Error [Code: {code} | HTTP {resp.status_code}]: {msg}"
        if log_id:
            detail += f" (log_id: {log_id})"
        LOGGER.error("TikTok API details: %s | Full response: %s", detail, data)
        
        if str(resp.status_code) == "403" or str(code) == "scope_not_authorized":
            detail += "\n\n👉 REASON: TikTok Developer Console'da App'inizin altında 'Content Posting API' ürünü ekli olmalı ve kullanıcı tekrar Authorize edilmelidir."
        raise ApiError(detail)
    return data


def groq_caption(api_key, video_filename):
    name = Path(video_filename).stem.replace('_',' ').replace('-',' ')
    system_msg = "You are an expert viral TikTok copywriter for thecaptionai.com (an AI caption generator app for content creators)."
    user_msg = (
        f"Write a viral, high-converting English TikTok caption for a video titled: '{name}'.\n"
        "STYLE REQUIREMENT:\n"
        "- Strong viral hook (e.g., 'Creators who don't know this app are crying rn 😭🔥', 'This AI tool feels illegal to know 🤫')\n"
        "- Natural, trendy creator tone with popular emojis.\n"
        "- Highlight how easy captions are with thecaptionai.com.\n"
        "- End with 4-5 viral hashtags like #captionai #foryou #contentcreatortips #ai #fyp.\n\n"
        "EXAMPLE FORMAT:\n"
        "Creators who don't know this app are crying rn 😭🔥 You'll never write a caption again #captionai #foryou #contentcreatortips #ai #fyp\n\n"
        "OUTPUT RULE: Return ONLY the raw caption text. No quotes, no explanations."
    )
    resp = HTTP.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            "max_tokens": 150,
            "temperature": 0.85
        },
        timeout=(10,30)
    )
    if not resp.ok: raise ApiError(f"Groq {resp.status_code}: {resp.text[:200]}")
    res_text = resp.json()["choices"][0]["message"]["content"].strip()
    return res_text.strip('"\'')[:2200]



@dataclass
class OAuthResult:
    access_token: str
    refresh_token: str
    expires_in: int


def _do_oauth(vault, cancelled):
    ck, cs = vault.app()
    if not all((ck, cs)): raise AppError("Save Client Key + Secret in API Keys tab first")
    parsed = urllib.parse.urlparse(REDIRECT_URI)
    state    = secrets.token_urlsafe(32)
    alphabet = string.ascii_letters + string.digits + "-._~"
    verifier  = "".join(secrets.choice(alphabet) for _ in range(64))
    challenge = hashlib.sha256(verifier.encode()).hexdigest()
    result = {}; event = threading.Event()
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state",[""])[0] != state:
                self.send_response(400); self.end_headers(); event.set(); return
            result["code"]  = q.get("code",  [""])[0]
            result["error"] = q.get("error_description", q.get("error",[""]))[0]
            body = b"<html><body style='font:16px system-ui;background:#0d1610;color:#00f5a0;padding:40px'>Authorization received. Close this tab.</body></html>"
            self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); event.set()
        def log_message(self,*_): return
    server = ThreadingHTTPServer((parsed.hostname, parsed.port), H); server.timeout = 0.5
    params = {"client_key":ck,"scope":"user.info.basic,video.publish","response_type":"code",
              "redirect_uri":REDIRECT_URI,"state":state,"code_challenge":challenge,"code_challenge_method":"S256"}
    webbrowser.open(TIKTOK_AUTH + "?" + urllib.parse.urlencode(params))
    deadline = time.monotonic() + 300
    try:
        while not event.is_set() and time.monotonic() < deadline:
            if cancelled(): raise Cancelled("Cancelled")
            server.handle_request()
    finally: server.server_close()
    if result.get("error"): raise ApiError(result["error"])
    code = result.get("code")
    if not code: raise ApiError("Authorization timed out")
    resp = HTTP.post(f"{TIKTOK_API}/v2/oauth/token/",
        headers={"Content-Type":"application/x-www-form-urlencoded"},
        data={"client_key":ck,"client_secret":cs,"code":code,
              "grant_type":"authorization_code","redirect_uri":REDIRECT_URI,"code_verifier":verifier},
        timeout=(15,45))
    data = _tt(resp)
    return OAuthResult(data["access_token"], data.get("refresh_token",""), int(data.get("expires_in",86400)))


def _access_token(vault, registry, account):
    acc, ref = vault.tokens(account["id"])
    if not acc: raise ApiError("No OAuth token -- authorize this profile first")
    expiry = account.get("token_expires_at")
    if expiry and parse_iso(expiry) > utc_now() + timedelta(minutes=5): return acc
    ck, cs = vault.app()
    if not all((ck, cs, ref)): raise ApiError("Token refresh failed -- credentials incomplete")
    resp = HTTP.post(f"{TIKTOK_API}/v2/oauth/token/",
        headers={"Content-Type":"application/x-www-form-urlencoded"},
        data={"client_key":ck,"client_secret":cs,"grant_type":"refresh_token","refresh_token":ref},
        timeout=(15,45))
    data = _tt(resp); new_acc = data["access_token"]
    vault.set_tokens(account["id"], new_acc, data.get("refresh_token", ref))
    registry.update_account(account["id"],
        token_expires_at=iso(utc_now()+timedelta(seconds=int(data.get("expires_in",86400)))))
    return new_acc


def _chunk_plan(size):
    if size <= 0: raise ApiError("Video is empty")
    M = 1024*1024
    if size <= 64*M: return size, 1
    chunk = 10*M; count = (size+chunk-1)//chunk
    if count > 1000: chunk=64*M; count=(size+chunk-1)//chunk
    if count > 1000: raise ApiError("Video too large")
    return chunk, count


def fetch_creator_info(token):
    try:
        resp = HTTP.post(
            f"{TIKTOK_API}/v2/post/publish/creator_info/query/",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            json={},
            timeout=(15, 30)
        )
        data = _tt(resp).get("data", {})
        return data
    except Exception as e:
        LOGGER.warning("Creator info query returned error, using fallback options: %s", e)
        return {}


def upload_video(vault, registry, account, video_path, caption, prog, cancelled):
    path = Path(video_path).expanduser().resolve()
    if not path.is_file(): raise AppError("Video not found")
    if path.suffix.lower() not in {".mp4",".mov",".m4v",".webm"}: raise AppError("Use mp4/mov/m4v/webm")
    token = _access_token(vault, registry, account)
    size  = path.stat().st_size; chunk_size, chunk_count = _chunk_plan(size)

    prog(3, "Checking TikTok Creator Capabilities...")
    creator_info = fetch_creator_info(token)
    allowed_privacy = creator_info.get("privacy_level_options", [])
    
    if "PUBLIC_TO_EVERYONE" in allowed_privacy:
        privacy_level = "PUBLIC_TO_EVERYONE"
    elif allowed_privacy:
        privacy_level = allowed_privacy[0]
    else:
        privacy_level = "PUBLIC_TO_EVERYONE"

    disable_comment = creator_info.get("comment_disabled", False)
    disable_duet = creator_info.get("duet_disabled", False)
    disable_stitch = creator_info.get("stitch_disabled", False)

    headers = {"Authorization":f"Bearer {token}","Content-Type":"application/json; charset=UTF-8"}
    prog(5, "Initializing Upload...")
    
    def try_init(p_level):
        post_info = {
            "title": caption,
            "privacy_level": p_level,
            "disable_comment": disable_comment,
            "disable_duet": disable_duet,
            "disable_stitch": disable_stitch,
            "video_cover_timestamp_ms": 1000
        }
        return HTTP.post(f"{TIKTOK_API}/v2/post/publish/video/init/", headers=headers,
            json={
                "post_info": post_info,
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": chunk_count
                }
            },
            timeout=(15,60))

    init_resp = try_init(privacy_level)
    
    # Check if client is unaudited for Public posting
    if not init_resp.ok:
        try:
            err_data = init_resp.json().get("error", {})
            err_code = str(err_data.get("code", ""))
        except Exception:
            err_code = ""
            
        if "unaudited_client" in err_code or err_code == "unaudited_client_can_only_post_to_private_accounts":
            LOGGER.warning("TikTok App is in Unaudited/Staging mode. Retrying with SELF_ONLY privacy level.")
            prog(7, "Unaudited App mode detected -- Retrying as Private (SELF_ONLY)...")
            init_resp = try_init("SELF_ONLY")

    d = _tt(init_resp).get("data",{})
    upload_url = d.get("upload_url")
    publish_id = d.get("publish_id")
    if not upload_url or not publish_id: raise ApiError("No upload URL / publish ID from TikTok")
    
    sent = 0
    with path.open("rb") as fh:
        for idx in range(chunk_count):
            if cancelled(): raise Cancelled("Upload cancelled")
            amount = min(chunk_size, size-sent); body = fh.read(amount)
            if len(body) != amount: raise ApiError("File changed during upload")
            end = sent + amount - 1
            cr = HTTP.put(upload_url, data=body,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(amount),
                    "Content-Range": f"bytes {sent}-{end}/{size}"
                },
                timeout=(30,240))
            if not cr.ok: raise ApiError(f"Chunk {idx+1} failed HTTP {cr.status_code}")
            sent = end + 1
            prog(10 + round(65 * sent / size), f"Uploading {idx+1}/{chunk_count}")
            
    prog(78, "Processing on TikTok...")
    return publish_id

def poll_status(vault, registry, account, publish_id, prog, cancelled, timeout=900):
    DONE={"PUBLISH_COMPLETE","SEND_TO_USER_INBOX"}; FAIL={"FAILED","PUBLISH_FAILED","DOWNLOAD_FAILED"}
    token=_access_token(vault,registry,account); deadline=time.monotonic()+timeout; interval=3.0; tick=0
    while time.monotonic()<deadline:
        if cancelled(): raise Cancelled("Cancelled")
        resp = HTTP.post(f"{TIKTOK_API}/v2/post/publish/status/fetch/",
            headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},
            json={"publish_id":publish_id}, timeout=(15,45))
        data=_tt(resp).get("data",{}); status=str(data.get("status","PROCESSING_UPLOAD"))
        tick=(tick+1)%20; prog(min(99,78+tick), status.replace("_"," ").title())
        if status in DONE: return status
        if status in FAIL: raise ApiError(f"TikTok failed: {data.get('fail_reason') or status}")
        LOGGER.info("Poll: %s", status); time.sleep(interval); interval=min(15.0,interval*1.3)
    raise ApiError("Publish timed out after 15 minutes")


class OAuthThread(QThread):
    succeeded = Signal(object); failed = Signal(str)
    def __init__(self, vault): super().__init__(); self.vault=vault; self._cancel=threading.Event()
    def cancel(self): self._cancel.set()
    def run(self):
        try: self.succeeded.emit(_do_oauth(self.vault, self._cancel.is_set))
        except Exception as e: LOGGER.exception("OAuth"); self.failed.emit(str(e) or type(e).__name__)


class UploadThread(QThread):
    progress=Signal(int,str); succeeded=Signal(str); failed=Signal(str)
    def __init__(self,vault,registry,account,video,caption):
        super().__init__(); self.vault=vault; self.registry=registry; self.account=account
        self.video=video; self.caption=caption; self._cancel=threading.Event()
    def cancel(self): self._cancel.set()
    def run(self):
        try:
            pid=upload_video(self.vault,self.registry,self.account,
                             self.video,self.caption,self.progress.emit,self._cancel.is_set)
            self.registry.update_account(self.account["id"],last_status="Processing...")
            status=poll_status(self.vault,self.registry,self.account,
                               pid,self.progress.emit,self._cancel.is_set)
            self.registry.update_account(self.account["id"],last_status=status); self.succeeded.emit(pid)
        except Exception as e:
            LOGGER.exception("Upload"); self.registry.update_account(self.account["id"],last_status="Failed")
            self.failed.emit(str(e) or type(e).__name__)


class GroqThread(QThread):
    succeeded=Signal(str); failed=Signal(str)
    def __init__(self,key,fname): super().__init__(); self.key=key; self.fname=fname
    def run(self):
        try: self.succeeded.emit(groq_caption(self.key,self.fname))
        except Exception as e: LOGGER.exception("Groq"); self.failed.emit(str(e) or type(e).__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.registry=Registry(DATA_DIR/"accounts.json"); self.vault=Vault()
        self._oauth_w=None; self._upload_w=None; self._groq_w=None
        self.setWindowTitle(APP_NAME); self.resize(1100,760); self.setMinimumSize(900,620)
        self._build_ui(); self._apply_theme(); self._refresh()

    def _build_ui(self):
        root=QWidget(); outer=QVBoxLayout(root)
        outer.setContentsMargins(28,22,28,28); outer.setSpacing(16)
        hdr=QHBoxLayout(); brand=QVBoxLayout(); brand.setSpacing(2)
        eye=QLabel("CAPTIONAI  /  TIKTOK PUBLISHER"); eye.setObjectName("eyebrow")
        tag=QLabel("English captions. Real reach."); tag.setObjectName("title")
        brand.addWidget(eye); brand.addWidget(tag); hdr.addLayout(brand); hdr.addStretch()
        self._pill=QLabel("READY"); self._pill.setObjectName("pill"); hdr.addWidget(self._pill)
        outer.addLayout(hdr)
        self._tabs=QTabWidget(); self._tabs.setDocumentMode(True)
        self._tabs.addTab(self._tab_accounts(),"Accounts")
        self._tabs.addTab(self._tab_upload(),"Upload & Share")
        self._tabs.addTab(self._tab_keys(),"API Keys")
        outer.addWidget(self._tabs,1); self.setCentralWidget(root)

    def _tab_accounts(self):
        page=QWidget(); outer=QHBoxLayout(page); outer.setContentsMargins(0,18,0,0); outer.setSpacing(20)
        left=QFrame(); left.setObjectName("panel"); box=QVBoxLayout(left)
        box.setContentsMargins(24,24,24,24); box.setSpacing(14)
        box.addWidget(self._sec("Add TikTok Account"))
        n=QLabel("Enter a display name. After adding, select it and click Authorize to connect via OAuth.")
        n.setWordWrap(True); n.setObjectName("muted"); box.addWidget(n)
        frm=QFormLayout(); self._pname=QLineEdit(); self._pname.setPlaceholderText("e.g. CaptionAI_Brand")
        frm.addRow("Profile name",self._pname); box.addLayout(frm)
        for txt,fn,prim in [("Add Account",self._add_profile,True),
                            ("Authorize Selected",self._authorize,False),
                            ("Remove Selected",self._remove_profile,False)]:
            b=QPushButton(txt)
            if prim: b.setObjectName("primary")
            b.clicked.connect(fn); box.addWidget(b)
        box.addStretch(); outer.addWidget(left,0)
        right=QVBoxLayout(); right.addWidget(self._sec("Registered Accounts"))
        self._utbl=QTableWidget(0,4)
        self._utbl.setHorizontalHeaderLabels(["Profile","Platform","Token","Status"])
        self._cfg_tbl(self._utbl); right.addWidget(self._utbl,1)
        outer.addLayout(right,1); return page

    def _tab_upload(self):
        page=QWidget(); outer=QVBoxLayout(page); outer.setContentsMargins(0,18,0,0); outer.setSpacing(18)
        ctrl=QFrame(); ctrl.setObjectName("panel"); grid=QGridLayout(ctrl)
        grid.setContentsMargins(26,24,26,24); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(14)
        grid.addWidget(QLabel("TikTok Account"),0,0)
        self._uacc=QComboBox(); grid.addWidget(self._uacc,0,1,1,3)
        grid.addWidget(QLabel("Video File"),1,0)
        self._uvid=QLineEdit(); self._uvid.setPlaceholderText("Select a video (.mp4 / .mov / .webm)"); self._uvid.setReadOnly(True)
        bbr=QPushButton("Browse..."); bbr.clicked.connect(self._browse)
        grid.addWidget(self._uvid,1,1,1,2); grid.addWidget(bbr,1,3)
        grid.addWidget(QLabel("Caption (EN)"),2,0)
        self._ucap=QLineEdit(); self._ucap.setPlaceholderText("Auto-generated by Groq, or type your own...")
        bgr=QPushButton("Generate with Groq"); bgr.clicked.connect(self._groq_gen)
        grid.addWidget(self._ucap,2,1,1,2); grid.addWidget(bgr,2,3)
        note=QLabel("Videos are uploaded as Public to Everyone -- required by TikTok Content Posting API.")
        note.setObjectName("muted"); note.setWordWrap(True); grid.addWidget(note,3,0,1,4)
        self._bup=QPushButton("Upload & Share Now"); self._bup.setObjectName("primary"); self._bup.clicked.connect(self._start_upload)
        self._bcn=QPushButton("Cancel"); self._bcn.setEnabled(False); self._bcn.clicked.connect(self._cancel_upload)
        row4=QHBoxLayout(); row4.addWidget(self._bup); row4.addWidget(self._bcn); row4.addStretch()
        grid.addLayout(row4,4,0,1,4); grid.setColumnStretch(1,1); outer.addWidget(ctrl)
        self._prog=QProgressBar(); self._prog.setRange(0,100); self._prog.setValue(0); outer.addWidget(self._prog)
        self._ltbl=QTableWidget(0,3)
        self._ltbl.setHorizontalHeaderLabels(["Account","Caption preview","Result"])
        self._cfg_tbl(self._ltbl); outer.addWidget(self._ltbl,1); return page

    def _tab_keys(self):
        page=QWidget(); outer=QHBoxLayout(page); outer.setContentsMargins(0,18,0,0)
        panel=QFrame(); panel.setObjectName("panel"); box=QVBoxLayout(panel)
        box.setContentsMargins(28,26,28,28); box.setSpacing(18)
        box.addWidget(self._sec("TikTok App Credentials"))
        n1=QLabel("Paste your production Client Key and Client Secret from developers.tiktok.com. Stored in OS keychain only.")
        n1.setWordWrap(True); n1.setObjectName("muted"); box.addWidget(n1)
        frm1=QFormLayout(); ck,_=self.vault.app()
        self._ck=QLineEdit(ck); self._ck.setPlaceholderText("awxxxxxxxxxxxxxxxx")
        self._cs=QLineEdit(); self._cs.setEchoMode(QLineEdit.Password); self._cs.setPlaceholderText("Client Secret (hidden)")
        frm1.addRow("Client Key",self._ck); frm1.addRow("Client Secret",self._cs); box.addLayout(frm1)
        btt=QPushButton("Save TikTok Keys"); btt.setObjectName("primary"); btt.clicked.connect(self._save_tt); box.addWidget(btt)
        sep=QFrame(); sep.setFrameShape(QFrame.HLine); box.addWidget(sep)
        box.addWidget(self._sec("Groq API Key"))
        n2=QLabel("Your Groq API key (console.groq.com). Used only to auto-generate English captions.")
        n2.setWordWrap(True); n2.setObjectName("muted"); box.addWidget(n2)
        frm2=QFormLayout(); self._gk=QLineEdit(); self._gk.setEchoMode(QLineEdit.Password)
        self._gk.setPlaceholderText("Saved -- paste to update" if self.vault.groq() else "gsk_...")
        frm2.addRow("Groq API Key",self._gk); box.addLayout(frm2)
        bgk=QPushButton("Save Groq Key"); bgk.setObjectName("primary"); bgk.clicked.connect(self._save_groq); box.addWidget(bgk)
        box.addStretch(); outer.addWidget(panel,1); outer.addStretch(1); return page

    @staticmethod
    def _sec(t): l=QLabel(t); l.setObjectName("section"); return l
    @staticmethod
    def _cfg_tbl(t):
        t.setAlternatingRowColors(True); t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setEditTriggers(QTableWidget.NoEditTriggers); t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        t.horizontalHeader().setStretchLastSection(True)
    def _uid(self):
        row=self._utbl.currentRow(); item=self._utbl.item(row,0)
        return item.data(Qt.UserRole) if item else ""
    def _status(self,t): self._pill.setText(t[:32].upper())
    def _err(self,msg): LOGGER.error("UI: %s",msg[:600]); QMessageBox.critical(self,APP_NAME,msg)

    def _add_profile(self):
        try: self.registry.add_account(self._pname.text()); self._pname.clear(); self._refresh()
        except Exception as e: self._err(str(e))
    def _remove_profile(self):
        uid=self._uid()
        if not uid: self._err("Select a profile first"); return
        self.registry.remove_account(uid); self.vault.del_tokens(uid); self._refresh()
    def _authorize(self):
        uid=self._uid()
        if not uid: self._err("Select a profile to authorize"); return
        if self._oauth_w and self._oauth_w.isRunning(): return
        self._status("AUTHORIZING"); w=OAuthThread(self.vault); self._oauth_w=w
        w.succeeded.connect(lambda r: self._oauth_done(uid,r))
        w.failed.connect(lambda m: (self._err(m),self._status("READY")))
        w.finished.connect(lambda: setattr(self,"_oauth_w",None)); w.start()
    def _oauth_done(self,uid,result):
        try:
            self.vault.set_tokens(uid,result.access_token,result.refresh_token)
            self.registry.update_account(uid,
                token_expires_at=iso(utc_now()+timedelta(seconds=result.expires_in)),
                last_status="Authorized")
            self._status("READY"); self._refresh()
            QMessageBox.information(self,APP_NAME,"Authorization successful! Ready to upload.")
        except Exception as e: self._err(str(e))

    def _browse(self):
        path,_=QFileDialog.getOpenFileName(self,"Select Video","","Videos (*.mp4 *.mov *.m4v *.webm)")
        if path:
            self._uvid.setText(path)
            if self.vault.groq() and not self._ucap.text().strip(): self._groq_gen()
    def _groq_gen(self):
        vid=self._uvid.text().strip()
        if not vid: self._err("Select a video file first"); return
        gk=self.vault.groq()
        if not gk: self._err("Save your Groq API key in API Keys tab first"); return
        if self._groq_w and self._groq_w.isRunning(): return
        self._status("GENERATING..."); w=GroqThread(gk,vid); self._groq_w=w
        w.succeeded.connect(lambda c: (self._ucap.setText(c),self._status("READY")))
        w.failed.connect(lambda m: (self._err(m),self._status("READY")))
        w.finished.connect(lambda: setattr(self,"_groq_w",None)); w.start()
    def _start_upload(self):
        if self._upload_w and self._upload_w.isRunning(): return
        uid=self._uacc.currentData()
        if not uid: self._err("No account selected"); return
        vid=self._uvid.text().strip(); cap=self._ucap.text().strip()
        if not vid: self._err("Select a video file first"); return
        if not cap: self._err("Caption required -- use Generate or type one"); return
        state=self.registry.snapshot()
        acc=next((a for a in state["accounts"] if a["id"]==uid),None)
        if not acc: self._err("Profile not found"); return
        tok,_=self.vault.tokens(uid)
        if not tok: self._err("Authorize this account first (Accounts tab)"); return
        self._prog.setValue(0); self._bup.setEnabled(False); self._bcn.setEnabled(True); self._status("UPLOADING")
        w=UploadThread(self.vault,self.registry,acc,vid,cap); self._upload_w=w
        w.progress.connect(lambda p,t:(self._prog.setValue(p),self._status(t[:32])))
        w.succeeded.connect(self._on_success); w.failed.connect(self._on_failed)
        w.finished.connect(self._on_done); w.start()
    def _cancel_upload(self):
        if self._upload_w: self._upload_w.cancel()
    def _on_success(self,pid):
        self._prog.setValue(100); self._status("PUBLISHED")
        name=self._uacc.currentText(); cap=self._ucap.text()
        row=self._ltbl.rowCount(); self._ltbl.insertRow(row)
        self._ltbl.setItem(row,0,QTableWidgetItem(name))
        self._ltbl.setItem(row,1,QTableWidgetItem(cap[:60]+("..." if len(cap)>60 else "")))
        self._ltbl.setItem(row,2,QTableWidgetItem(f"PUBLISHED OK -- {pid[:20]}"))
        QMessageBox.information(self,APP_NAME,f"Video published!\n\nPublish ID: {pid}")
        self._uvid.clear(); self._ucap.clear()
    def _on_failed(self,msg):
        self._status("FAILED"); row=self._ltbl.rowCount(); self._ltbl.insertRow(row)
        self._ltbl.setItem(row,0,QTableWidgetItem(self._uacc.currentText()))
        self._ltbl.setItem(row,1,QTableWidgetItem("--"))
        self._ltbl.setItem(row,2,QTableWidgetItem(f"FAILED: {msg[:80]}"))
        self._err(f"Upload failed:\n{msg}")
    def _on_done(self):
        self._bup.setEnabled(True); self._bcn.setEnabled(False)
        w=self._upload_w
        if w: w.deleteLater()
        self._upload_w=None
        if self._pill.text() not in ("PUBLISHED","FAILED"): self._status("READY")
    def _save_tt(self):
        ck=self._ck.text().strip(); cs=self._cs.text().strip()
        if not ck: self._err("Client Key required"); return
        if not cs: self._err("Client Secret required"); return
        self.vault.set_app(ck,cs); self._cs.clear()
        QMessageBox.information(self,APP_NAME,"TikTok credentials saved to OS keychain.")
    def _save_groq(self):
        k=self._gk.text().strip()
        if not k: self._err("Paste Groq API key first"); return
        self.vault.set_groq(k); self._gk.clear(); self._gk.setPlaceholderText("Saved -- paste to update")
        QMessageBox.information(self,APP_NAME,"Groq API key saved to OS keychain.")
    def _refresh(self):
        try: state=self.registry.snapshot()
        except Exception as e: self._err(str(e)); return
        accounts=state["accounts"]
        self._utbl.setRowCount(len(accounts))
        for row,acc in enumerate(accounts):
            vals=[acc["name"],acc["platform"],
                  "Ready" if acc.get("token_expires_at") else "Not authorized",
                  acc.get("last_status","--")]
            for col,v in enumerate(vals):
                item=QTableWidgetItem(str(v))
                if col==0: item.setData(Qt.UserRole,acc["id"])
                self._utbl.setItem(row,col,item)
        cur=self._uacc.currentData()
        self._uacc.blockSignals(True); self._uacc.clear()
        for acc in accounts: self._uacc.addItem(acc["name"],acc["id"])
        idx=self._uacc.findData(cur)
        if idx>=0: self._uacc.setCurrentIndex(idx)
        self._uacc.blockSignals(False)

    def _apply_theme(self):
        pal=QPalette()
        pal.setColor(QPalette.Window,          QColor("#0a0f0d"))
        pal.setColor(QPalette.WindowText,      QColor("#ddeae0"))
        pal.setColor(QPalette.Base,            QColor("#0d1410"))
        pal.setColor(QPalette.AlternateBase,   QColor("#111812"))
        pal.setColor(QPalette.Text,            QColor("#ddeae0"))
        pal.setColor(QPalette.Button,          QColor("#18201c"))
        pal.setColor(QPalette.ButtonText,      QColor("#ddeae0"))
        pal.setColor(QPalette.Highlight,       QColor("#00f5a0"))
        pal.setColor(QPalette.HighlightedText, QColor("#031209"))
        self.setPalette(pal)
        self.setStyleSheet("""
            QWidget{color:#ddeae0;font-family:'Segoe UI','Inter',sans-serif;font-size:13px;}
            QMainWindow{background:#0a0f0d;}
            QTabWidget::pane{border:0;background:transparent;}
            QTabBar::tab{padding:12px 22px;color:#5a7a6a;border-bottom:2px solid transparent;font-weight:600;}
            QTabBar::tab:selected{color:#ddeae0;border-bottom-color:#00f5a0;}
            QTabBar::tab:hover{color:#a0c8b0;}
            QFrame#panel{background:#111814;border:1px solid #1e2e24;border-radius:14px;}
            QLabel#eyebrow{color:#00f5a0;font-size:10px;font-weight:700;letter-spacing:2.5px;}
            QLabel#title{font-size:28px;font-weight:700;}
            QLabel#section{font-size:17px;font-weight:700;}
            QLabel#muted{color:#6a8878;font-size:12px;}
            QLabel#pill{background:#0b2818;color:#00f5a0;padding:7px 16px;border-radius:14px;font-weight:700;font-size:11px;letter-spacing:1.5px;}
            QLineEdit,QComboBox{background:#0c1410;border:1px solid #253024;border-radius:8px;padding:9px 12px;min-height:20px;}
            QLineEdit:focus,QComboBox:focus{border:1px solid #00f5a0;}
            QPushButton{background:#181f1b;border:1px solid #253024;border-radius:8px;padding:9px 18px;min-height:22px;font-weight:500;}
            QPushButton:hover{background:#1e2820;border-color:#356040;}
            QPushButton:pressed{background:#0e1510;}
            QPushButton:disabled{color:#2a4030;border-color:#1a2018;}
            QPushButton#primary{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #00f5a0,stop:1 #00c87a);color:#031a0a;border:0;font-weight:700;}
            QPushButton#primary:hover{background:#00ffaa;}
            QPushButton#primary:pressed{background:#00b870;}
            QTableWidget{background:#0d1411;alternate-background-color:#111814;border:1px solid #1e2e24;border-radius:10px;gridline-color:#1a2418;}
            QHeaderView::section{background:#161e1a;color:#6a8878;padding:9px;border:0;border-bottom:1px solid #253024;font-weight:700;font-size:11px;}
            QTableWidget::item:selected{background:#0c2e18;}
            QProgressBar{background:#111814;border:1px solid #253024;border-radius:7px;text-align:center;min-height:22px;color:#ddeae0;font-weight:600;}
            QProgressBar::chunk{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #00f5a0,stop:1 #00c87a);border-radius:6px;}
            QScrollBar:vertical{background:#0a0f0d;width:8px;border-radius:4px;}
            QScrollBar::handle:vertical{background:#253024;border-radius:4px;min-height:28px;}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
        """)


def main():
    app=QApplication(sys.argv)
    app.setApplicationName(APP_NAME); app.setOrganizationName("CaptionAI")
    app.setStyle("Fusion"); app.setFont(QFont("Segoe UI",10))
    win=MainWindow(); win.show(); return app.exec()

if __name__=="__main__":
    raise SystemExit(main())
