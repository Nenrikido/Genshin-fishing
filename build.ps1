# Build GenshinFishing.exe. Usage:  .\build.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

python -c "import PyInstaller" 2>$null
if (-not $?) {
    Write-Host "installing pyinstaller..." -ForegroundColor Cyan
    python -m pip install -r requirements-dev.txt
}

Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
python -m PyInstaller --noconfirm --clean GenshinFishing.spec
if (-not $?) { throw "build failed" }

$exe = "dist\GenshinFishing.exe"
if (-not (Test-Path $exe)) { throw "no exe produced" }
$mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)

# setting.ini lives beside the exe, not inside it, so ship the template
if (-not (Test-Path "dist\setting.ini")) {
    Copy-Item "setting.ini.example" "dist\setting.ini"
}

Write-Host ""
Write-Host "built $exe ($mb MB)" -ForegroundColor Green
Write-Host "run it from dist\ - it will ask for admin rights (Genshin ignores"
Write-Host "input from a non-elevated process). Edit dist\setting.ini to configure."
