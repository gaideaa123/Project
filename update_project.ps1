$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$repo = "https://raw.githubusercontent.com/gaideaa123/Project/main"
$files = @(
    "app.py", "app_tr.py", "run_tr.py", "oauth_helper.py", "smoke_test.py",
    "requirements.txt", "README.md", "TURKCE_KURULUM.md", ".gitignore"
)

Write-Host "SignalDesk dosyalari ayni surume getiriliyor..." -ForegroundColor Cyan
foreach ($file in $files) {
    $target = Join-Path $PSScriptRoot $file
    $temporary = "$target.download"
    Invoke-WebRequest -Uri "$repo/$file" -OutFile $temporary -UseBasicParsing
    if ((Get-Item $temporary).Length -eq 0) { throw "$file bos indirildi" }
    Move-Item $temporary $target -Force
    Write-Host "  OK $file"
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw ".venv bulunamadi. Once: py -3.11 -m venv .venv" }
& $python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Bagimlilik kurulumu basarisiz" }

$env:QT_QPA_PLATFORM = "offscreen"
& $python (Join-Path $PSScriptRoot "smoke_test.py")
$testCode = $LASTEXITCODE
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
if ($testCode -ne 0) { throw "Duman testi basarisiz" }

Write-Host "`nHazir. Turkce uygulamayi su komutla ac:" -ForegroundColor Green
Write-Host ".\.venv\Scripts\python.exe .\run_tr.py" -ForegroundColor Yellow
