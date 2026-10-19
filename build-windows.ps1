param(
    [switch]$BundleModels
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "O build Windows deve ser executado no Windows. PyInstaller não faz cross-compile deste projeto."
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "=== PersonOfInterest build — Windows x64 ===" -ForegroundColor Cyan

$PythonCommand = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCommand = @("py", "-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCommand = @("python")
} else {
    throw "Python 3.11+ não encontrado."
}

$BuildVenv = Join-Path $Root ".build-venv"
$BuildPython = Join-Path $BuildVenv "Scripts\python.exe"
if (-not (Test-Path $BuildPython)) {
    Write-Host "Criando ambiente isolado de build..."
    if ($PythonCommand.Count -eq 2) {
        & $PythonCommand[0] $PythonCommand[1] -m venv $BuildVenv
    } else {
        & $PythonCommand[0] -m venv $BuildVenv
    }
}

Write-Host "Instalando dependências de runtime e build..."
& $BuildPython -m pip install --upgrade pip
& $BuildPython -m pip install -r (Join-Path $Root "backend\requirements.txt") -r (Join-Path $Root "packaging\requirements-build.txt")

$BinDir = Join-Path $Root "bin"
$Go2rtcExe = Join-Path $BinDir "go2rtc.exe"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
if (-not (Test-Path $Go2rtcExe)) {
    Write-Host "Baixando go2rtc Windows 64-bit para o pacote..."
    $ZipPath = Join-Path $env:TEMP "poi_go2rtc_win64.zip"
    $ExtractPath = Join-Path $env:TEMP ("poi_go2rtc_build_" + [guid]::NewGuid().ToString("N"))
    Invoke-WebRequest -Uri "https://github.com/AlexxIT/go2rtc/releases/latest/download/go2rtc_win64.zip" -OutFile $ZipPath -UseBasicParsing
    New-Item -ItemType Directory -Force -Path $ExtractPath | Out-Null
    Expand-Archive -Path $ZipPath -DestinationPath $ExtractPath -Force
    $Downloaded = Get-ChildItem -Path $ExtractPath -Filter "go2rtc.exe" -Recurse | Select-Object -First 1
    if (-not $Downloaded) { throw "go2rtc.exe não encontrado no pacote baixado." }
    Copy-Item $Downloaded.FullName $Go2rtcExe -Force
    Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue
    Remove-Item $ExtractPath -Recurse -Force -ErrorAction SilentlyContinue
}

function Ensure-Model([string]$Path, [string]$Url, [long]$MinimumBytes, [string]$Label) {
    if ((Test-Path $Path) -and (Get-Item $Path).Length -ge $MinimumBytes) { return }
    Write-Host "Baixando $Label para incluir no pacote..." -ForegroundColor Yellow
    $Part = "$Path.part"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    Remove-Item $Part -Force -ErrorAction SilentlyContinue
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Part -UseBasicParsing
        if ((Get-Item $Part).Length -lt $MinimumBytes) { throw "Arquivo de modelo incompleto." }
        Move-Item $Part $Path -Force
    } catch {
        Remove-Item $Part -Force -ErrorAction SilentlyContinue
        throw
    }
}

if ($BundleModels) {
    $ModelsDir = Join-Path $Root "data\models"
    Ensure-Model (Join-Path $ModelsDir "yolox_tiny.onnx") "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx" 1000000 "YOLOX-Tiny"
    Ensure-Model (Join-Path $ModelsDir "face_detection_yunet_2023mar.onnx") "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" 150000 "YuNet"
    Ensure-Model (Join-Path $ModelsDir "face_recognition_sface_2021dec.onnx") "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface_2021dec.onnx" 10000000 "SFace"
    Ensure-Model (Join-Path $ModelsDir "osnet_x0_25_msmt17.onnx") "https://huggingface.co/anriha/osnet_x0_25_msmt17/resolve/main/osnet_x0_25_msmt17.onnx?download=true" 700000 "OSNet"
    $env:POI_BUNDLE_MODELS = "1"
} else {
    $env:POI_BUNDLE_MODELS = "0"
}

Write-Host "Empacotando com PyInstaller..."
& $BuildPython -m PyInstaller --clean --noconfirm (Join-Path $Root "packaging\PersonOfInterest.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller encerrou com código $LASTEXITCODE." }

$Exe = Join-Path $Root "dist\PersonOfInterest\PersonOfInterest.exe"
if (-not (Test-Path $Exe)) { throw "Build concluído sem gerar $Exe" }

Write-Host ""
Write-Host "Build Windows concluído." -ForegroundColor Green
Write-Host "Executável: $Exe" -ForegroundColor Green
if ($BundleModels) {
    Write-Host "Modelos ONNX incluídos no pacote." -ForegroundColor DarkGray
} else {
    Write-Host "Modelos ONNX serão baixados uma única vez no primeiro uso." -ForegroundColor DarkGray
}
Write-Host "Whisper continua baixando apenas os modelos selecionados pelo usuário quando necessário." -ForegroundColor DarkGray
