$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$repo = "https://raw.githubusercontent.com/gaideaa123/Project/main"
$files = @(
 ".github/workflows/python-smoke.yml", ".gitignore", "requirements.txt", "update_project.ps1",
 "app.py", "app_tr.py", "run_tr.py", "run_one_click.py", "one_click_tr.py",
 "oauth_helper.py", "web_uploader.py", "web_upload_engine.py", "web_gui_integration.py",
 "tiktok_login.py", "tiktok_overlays.py", "copyright_dialog.py", "copyright_policy.py",
 "preflight_hook.py", "content_preflight.py", "video_variants.py", "uniquizer_tab.py",
 "session_gui.py", "session_account_gui.py", "publishing_flow_gui.py", "direct_connection_policy.py", "target_reachability.py", "sitecustomize.py",
 "media_qa.py", "antibot_resilience.py", "antibot_sandbox.py", "network_identity.py",
 "network_identity_gui.py", "proxy_health.py", "proxy_publisher.py", "socks_bridge.py",
 "smoke_test.py", "preflight_smoke.py", "media_qa_smoke.py", "antibot_resilience_smoke.py",
 "antibot_sandbox_smoke.py", "runtime_contract_smoke.py", "feature_presence_contract_test.py",
 "publish_flow_contract_test.py", "proxy_web_inheritance_test.py", "socks5_proxy_test.py",
 "socks5_health_bridge_test.py", "guide_proxy_assignment_test.py", "direct_connection_policy_test.py", "target_reachability_test.py",
 "session_publish_unit_tests.py", "content_check_overlay_test.py", "updater_contract_test.py", "README.md", "TURKCE_KURULUM.md", "WEB_GUI_KURULUM.md", "WEB_YUKLEME_KURULUM.md"
)
$stage = Join-Path $env:TEMP ("signaldesk-update-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
 Write-Host "SignalDesk dosyalari ayni surume getiriliyor..." -ForegroundColor Cyan
 foreach ($file in $files) {
  $download = Join-Path $stage $file
  New-Item -ItemType Directory -Force -Path (Split-Path $download) | Out-Null
  Invoke-WebRequest -Uri "$repo/$file" -OutFile $download -UseBasicParsing
  if ((Get-Item $download).Length -eq 0) { throw "$file bos indirildi" }
 }
 $python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
 if (-not (Test-Path $python)) { throw ".venv bulunamadi. Once: py -3.11 -m venv .venv" }
 & $python -m compileall -q $stage
 if ($LASTEXITCODE -ne 0) { throw "Indirilen Python dosyalari derlenemedi" }
 foreach ($file in $files) {
  $target = Join-Path $PSScriptRoot $file
  New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
  Move-Item (Join-Path $stage $file) $target -Force
  Write-Host " OK $file"
 }
 & $python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
 if ($LASTEXITCODE -ne 0) { throw "Bagimlilik kurulumu basarisiz" }
 & $python -m playwright install chromium
 if ($LASTEXITCODE -ne 0) { throw "Playwright Chromium kurulumu basarisiz" }
 $env:QT_QPA_PLATFORM = "offscreen"
 & $python -m unittest -v (Join-Path $PSScriptRoot "session_publish_unit_tests.py")
 if ($LASTEXITCODE -ne 0) { throw "Session ID bootstrap testi basarisiz" }
 & $python (Join-Path $PSScriptRoot "content_check_overlay_test.py")
 if ($LASTEXITCODE -ne 0) { throw "Icerik kontrolu Ac testi basarisiz" }
 & $python (Join-Path $PSScriptRoot "socks5_proxy_test.py")
 if ($LASTEXITCODE -ne 0) { throw "SOCKS5 bridge testi basarisiz" }
 & $python (Join-Path $PSScriptRoot "socks5_health_bridge_test.py")
 if ($LASTEXITCODE -ne 0) { throw "SOCKS5 saglik testi basarisiz" }
 & $python (Join-Path $PSScriptRoot "guide_proxy_assignment_test.py")
 if ($LASTEXITCODE -ne 0) { throw "Guide proxy atama testi basarisiz" }
 & $python (Join-Path $PSScriptRoot "direct_connection_policy_test.py")
 if ($LASTEXITCODE -ne 0) { throw "Direct IP yayin testi basarisiz" }
 & $python (Join-Path $PSScriptRoot "target_reachability_test.py")
 if ($LASTEXITCODE -ne 0) { throw "TikTok hedef erisim testi basarisiz" }
 & $python (Join-Path $PSScriptRoot "runtime_contract_smoke.py")
 if ($LASTEXITCODE -ne 0) { throw "app_tr akis testi basarisiz" }
 & $python (Join-Path $PSScriptRoot "smoke_test.py")
 if ($LASTEXITCODE -ne 0) { throw "Duman testi basarisiz" }
 Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
 Write-Host "`nHazir. Tum eski SignalDesk pencerelerini kapatip calistir:" -ForegroundColor Green
 Write-Host ".\.venv\Scripts\python.exe .\app_tr.py" -ForegroundColor Yellow
}
finally {
 Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
}
