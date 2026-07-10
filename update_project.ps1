$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repo = "https://raw.githubusercontent.com/gaideaa123/Project/main"
$files = @(
    "app.py",
    "app_tr.py",
    "oauth_helper.py",
    "smoke_test.py",
    "requirements.txt",
    "README.md",
    "TURKCE_KURULUM.md",
    ".gitignore"
)

Write-Host "SignalDesk dosyalari guncelleniyor..." -ForegroundColor Cyan

foreach ($file in $files) {
    $url = "$repo/$file"
    $target = Join-Path $PSScriptRoot $file
    $temporary = "$target.download"
    Write-Host "  -> $file"
    Invoke-WebRequest -Uri $url -OutFile $temporary -UseBasicParsing
    if ((Get-Item $temporary).Length -eq 0) {
        throw "$file bos indirildi"
    }
    Move-Item -Path $temporary -Destination $target -Force
}

Write-Host "Bagimliliklar dogrulaniyor..." -ForegroundColor Cyan
& "$PSScriptRoot\.venv\Scripts\python.exe" -m pip install -r "$PSScriptRoot\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "pip install basarisiz" }

Write-Host "Duman testleri calistiriliyor..." -ForegroundColor Cyan
$env:QT_QPA_PLATFORM = "offscreen"
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\smoke_test.py"
if ($LASTEXITCODE -ne 0) { throw "Duman testi basarisiz" }
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue

Write-Host "`nGuncelleme tamam. Uygulamayi acmak icin:" -ForegroundColor Green
Write-Host ".\.venv\Scripts\python.exe .\app_tr.py" -ForegroundColor Yellow
