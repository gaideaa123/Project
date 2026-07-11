from __future__ import annotations

"""AST-backed contract test for the supported app_tr workflow."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def tree(name: str) -> ast.Module:
    return ast.parse((ROOT / name).read_text(encoding="utf-8"), filename=name)


def text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def functions(module: ast.Module) -> set[str]:
    return {node.name for node in ast.walk(module) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def calls(module: ast.Module) -> set[str]:
    result = set()
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name):
            result.add(target.id)
        elif isinstance(target, ast.Attribute):
            parts = [target.attr]
            value = target.value
            while isinstance(value, ast.Attribute):
                parts.append(value.attr)
                value = value.value
            if isinstance(value, ast.Name):
                parts.append(value.id)
            result.add(".".join(reversed(parts)))
    return result


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)
    print("OK:", message)


def main() -> None:
    app = tree("app_tr.py")
    uploader = tree("web_uploader.py")
    login = tree("tiktok_login.py")
    variants = tree("video_variants.py")
    startup = text("sitecustomize.py")

    app_calls = calls(app)
    login_functions = functions(login)
    uploader_functions = functions(uploader)
    variant_functions = functions(variants)

    require("tiktok_login.install" in app_calls, "session/preflight uploader kurulumu")
    require("web_uploader.prepare_upload" in app_calls, "app_tr web uploader çağrısı")
    require("bootstrap_session" in login_functions, "Session ID kalıcı profil bootstrapı")
    require("wait_for_upload_after_login" in login_functions, "session doğrulama bekleyicisi")
    require("confirm_publish_dialog" in uploader_functions, "telif yayın kapısı")
    require("wait_for_publish_result" in uploader_functions, "yayın sonucu doğrulaması")
    require("create_variants" in variant_functions, "numaralı varyasyon motoru")
    require("requests.post =" not in startup and "QLabel.__init__" not in startup,
            "global network/Qt monkey patch yok")

    app_source = text("app_tr.py")
    require("for profile, video in self.assignments" in app_source,
            "hesaplar sırayla işleniyor")
    require("paths[index]" in app_source and "enumerate(names)" in app_source,
            "1.mp4, 2.mp4 profil sırası korunuyor")
    require("publish=True" in app_source, "otomatik Publish etkin")
    print("\nAPP_TR DAVRANIŞ SÖZLEŞMESİ GEÇTİ")


if __name__ == "__main__":
    main()
