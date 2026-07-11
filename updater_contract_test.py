from __future__ import annotations

from pathlib import Path


def main() -> None:
 text = Path("update_project.ps1").read_text(encoding="utf-8")
 required = (
  "update_project.ps1", "network_identity.py", "proxy_health.py", "socks_bridge.py",
  "web_uploader.py", "requirements.txt", "socks5_proxy_test.py",
  "socks5_health_bridge_test.py", "updater_contract_test.py",
 )
 for name in required:
  assert f'"{name}"' in text, f"Updater eksik: {name}"
 assert "pip install -r" in text
 assert 'socks5_proxy_test.py")' in text
 assert 'socks5_health_bridge_test.py")' in text
 print("OK: Windows updater kendisini, SOCKS5 runtime ve testlerini indiriyor")


if __name__ == "__main__":
 main()
