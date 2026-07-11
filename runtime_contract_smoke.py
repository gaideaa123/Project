from __future__ import annotations

"""Static contract test for the supported direct app_tr.py workflow."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def source(name: str) -> str:
    value = (ROOT / name).read_text(encoding="utf-8")
    ast.parse(value, filename=name)
    return value


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)
    print("OK:", message)


def main() -> None:
    app_tr = source("app_tr.py")
    uploader = source("web_uploader.py")
    login = source("tiktok_login.py")
    variants = source("video_variants.py")
    startup = source("sitecustomize.py")

    require("tiktok_login.install(web_uploader)" in app_tr, "session/preflight uploader kurulumu")
    require("for profile, video in self.assignments" in app_tr, "hesaplar sırayla işleniyor")
    require("paths[index]" in app_tr and "enumerate(names)" in app_tr,
            "1.mp4, 2.mp4 sıralı profil eşleşmesi")
    require("AzureTitleClient" in app_tr and "requests.post" in app_tr,
            "Azure caption app_tr içinde açık entegrasyon")
    require("web_uploader.prepare_upload" in app_tr and "publish=True" in app_tr,
            "her atama web uploader'a gidiyor")
    require("finally:" in login and "previous_confirm" in login,
            "profil wrapper'ı hata halinde geri yükleniyor")
    require("with _INSTALL_LOCK" in login, "profil uploader sözleşmesi yarışa kapalı")
    require("confirm_publish_dialog" in uploader and "wait_for_publish_result" in uploader,
            "telif kapısı ve yayın sonucu doğrulaması mevcut")
    require("create_variants" in variants and 'f"{index}.mp4"' in variants,
            "numaralı varyasyon üretimi mevcut")
    require("requests.post =" not in startup and "QLabel.__init__" not in startup,
            "global network/Qt monkey patch kaldırıldı")
    print("\nAPP_TR SIRALI AKIŞ SÖZLEŞMESİ GEÇTİ")


if __name__ == "__main__":
    main()
