$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "=== PersonOfInterest setup (Windows) ===" -ForegroundColor Cyan

$PythonCommand = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = @("py", "-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = @("python")
} else {
    throw "Python 3 não encontrado. Instale Python 3.11+ e execute novamente."
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Criando ambiente virtual..."
    if ($PythonCommand.Count -eq 2) {
        & $PythonCommand[0] $PythonCommand[1] -m venv .venv
    } else {
        & $PythonCommand[0] -m venv .venv
    }
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
Write-Host "Instalando dependências Python..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $Root "backend\requirements.txt")

$BinDir = Join-Path $Root "bin"
$Go2rtcExe = Join-Path $BinDir "go2rtc.exe"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

if (-not (Test-Path $Go2rtcExe)) {
    Write-Host "Baixando go2rtc para Windows 64-bit..."
    $ZipPath = Join-Path $env:TEMP "go2rtc_win64.zip"
    $ExtractPath = Join-Path $env:TEMP ("poi_go2rtc_" + [guid]::NewGuid().ToString("N"))
    Invoke-WebRequest -Uri "https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_win64.zip" -OutFile $ZipPath
    New-Item -ItemType Directory -Force -Path $ExtractPath | Out-Null
    Expand-Archive -Path $ZipPath -DestinationPath $ExtractPath -Force
    $DownloadedExe = Get-ChildItem -Path $ExtractPath -Filter "go2rtc.exe" -Recurse | Select-Object -First 1
    if (-not $DownloadedExe) {
        throw "O executável go2rtc.exe não foi encontrado no pacote baixado."
    }
    Copy-Item $DownloadedExe.FullName $Go2rtcExe -Force
    Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue
    Remove-Item $ExtractPath -Recurse -Force -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "data") | Out-Null

Write-Host ""
Write-Host "Setup concluído." -ForegroundColor Green
Write-Host "Agora execute: .\start.ps1" -ForegroundColor Green
