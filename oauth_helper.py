from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
REDIRECT_URI = os.getenv("TIKTOK_REDIRECT_URI", "http://127.0.0.1:3455/callback/")
SCOPES = os.getenv("TIKTOK_SCOPES", "user.info.basic,video.publish")


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def main() -> None:
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
    if not client_key or not client_secret:
        raise SystemExit("Önce TIKTOK_CLIENT_KEY ve TIKTOK_CLIENT_SECRET ortam değişkenlerini ayarlayın.")

    parsed = urllib.parse.urlparse(REDIRECT_URI)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.port:
        raise SystemExit("Bu yardımcı yalnızca port içeren localhost yönlendirme adresini destekler.")

    state = secrets.token_urlsafe(32)
    verifier = b64url(secrets.token_bytes(64))
    challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    result: dict[str, str] = {}
    event = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write("Gecersiz state degeri".encode("utf-8"))
                event.set()
                return
            result["code"] = query.get("code", [""])[0]
            result["error"] = query.get("error", [""])[0]
            result["error_description"] = query.get("error_description", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<html><body style='font-family:system-ui;background:#151813;color:#eee;padding:40px'>"
                "<h2>Yetkilendirme tamamlandı</h2><p>Bu sekmeyi kapatıp terminale dönebilirsiniz.</p>"
                "</body></html>".encode("utf-8")
            )
            event.set()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer((parsed.hostname, parsed.port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    params = {
        "client_key": client_key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    print("Tarayıcı açılıyor. TikTok hesabınızla izin verin.")
    print("Açılmazsa bu adresi tarayıcıya yapıştırın:\n", url)
    webbrowser.open(url)

    if not event.wait(timeout=300):
        server.shutdown()
        raise SystemExit("5 dakika içinde yanıt gelmedi. İşlem iptal edildi.")
    server.shutdown()
    if result.get("error"):
        raise SystemExit(f"TikTok hatası: {result['error']} {result.get('error_description', '')}")
    code = result.get("code", "")
    if not code:
        raise SystemExit("Yetkilendirme kodu alınamadı.")

    response = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
        timeout=45,
    )
    try:
        payload = response.json()
    except ValueError:
        raise SystemExit(f"TikTok JSON döndürmedi: HTTP {response.status_code} {response.text[:500]}")
    if not response.ok or "access_token" not in payload:
        raise SystemExit("Belirteç alınamadı:\n" + json.dumps(payload, indent=2, ensure_ascii=False))

    print("\nBAŞARILI. Aşağıdaki değerleri SignalDesk Profil Yönetimi ekranına girin.")
    print("Erişim belirteci:")
    print(payload["access_token"])
    print("\nYenileme belirteci:")
    print(payload.get("refresh_token", ""))
    print("\nKapsamlar:", payload.get("scope", SCOPES))
    print("Erişim süresi (saniye):", payload.get("expires_in", "bilinmiyor"))
    print("\nBu terminal çıktısını paylaşmayın veya Git'e eklemeyin.")


if __name__ == "__main__":
    main()
