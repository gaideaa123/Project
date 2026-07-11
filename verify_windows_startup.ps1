$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    throw "Sanal ortam bulunamadı: .venv\Scripts\python.exe"
}

& ".\.venv\Scripts\python.exe" ".\verify_windows_startup.py"
if ($LASTEXITCODE -ne 0) {
    throw "app_tr başlangıç doğrulaması başarısız"
}

Write-Host "OK: Artık .\.venv\Scripts\python.exe .\app_tr.py çalıştırabilirsiniz" -ForegroundColor Green
