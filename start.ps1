param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$PythonExe = Join-Path $Root ".venv\Scripts\python.exe"
$Go2rtcExe = Join-Path $Root "bin\go2rtc.exe"
$RuntimeConfig = Join-Path $Root "data\go2rtc.runtime.yaml"
$Requirements = Join-Path $Root "backend\requirements.txt"

if (-not (Test-Path $PythonExe) -or -not (Test-Path $Go2rtcExe)) {
    throw "Instalacao incompleta. Execute .\setup.ps1 primeiro."
}

Write-Host "Verificando dependencias da V2..." -ForegroundColor DarkGray
$oldErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $PythonExe -c "import cv2, numpy, sys; ok = hasattr(cv2, 'HOGDescriptor') and int(cv2.__version__.split('.')[0]) < 5; sys.exit(0 if ok else 2)" *> $null
    $visionDepsExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $oldErrorActionPreference
}

if ($visionDepsExitCode -ne 0) {
    Write-Host "Ajustando dependencias de visao (OpenCV 4.x)..." -ForegroundColor Yellow
    & $PythonExe -m pip install --upgrade -r $Requirements
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao instalar as dependencias da V2."
    }
}

& $PythonExe -c "import cv2, numpy, sys; assert hasattr(cv2, 'HOGDescriptor'), 'OpenCV sem HOGDescriptor'; assert int(cv2.__version__.split('.')[0]) < 5, 'OpenCV 5 nao e suportado pelo detector atual'; print('OpenCV', cv2.__version__, '| NumPy', numpy.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "OpenCV/NumPy nao estao compativeis com o detector da V2."
}

$env:DATA_DIR = Join-Path $Root "data"
$env:FRONTEND_DIR = Join-Path $Root "frontend"
$env:GO2RTC_API_URL = "http://127.0.0.1:1984"
$env:GO2RTC_BROWSER_BASE = "direct"

New-Item -ItemType Directory -Force -Path (Join-Path $Root "data") | Out-Null
$runtimeYaml = @'
api:
  listen: ":1984"
rtsp:
  listen: ":8554"
webrtc:
  listen: ":8555"
streams: {}
log:
  level: info
'@
[System.IO.File]::WriteAllText($RuntimeConfig, $runtimeYaml, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "=== PersonOfInterest V2 ===" -ForegroundColor Cyan
Write-Host "Iniciando go2rtc..."
# Use a relative config path so Windows usernames/paths containing spaces do not get split by Start-Process.
$Go2rtc = Start-Process -FilePath $Go2rtcExe -ArgumentList @("-c", "data\go2rtc.runtime.yaml") -WorkingDirectory $Root -PassThru -NoNewWindow

$Backend = $null
try {
    $go2rtcReady = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:1984/api" -UseBasicParsing -TimeoutSec 1 | Out-Null
            $go2rtcReady = $true
            break
        } catch {
            Start-Sleep -Milliseconds 300
        }
    }
    if (-not $go2rtcReady) {
        throw "go2rtc nao respondeu na porta 1984."
    }

    Write-Host "Iniciando API, timeline, visao e interface em http://localhost:8080 ..."
    $Backend = Start-Process -FilePath $PythonExe -ArgumentList @(
        "-m", "uvicorn", "app.main:app",
        "--app-dir", "backend",
        "--host", "0.0.0.0",
        "--port", "8080"
    ) -WorkingDirectory $Root -PassThru -NoNewWindow

    $backendReady = $false
    for ($i = 0; $i -lt 60; $i++) {
        if ($Backend.HasExited) {
            throw "O backend encerrou durante a inicializacao."
        }
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:8080/api/health" -UseBasicParsing -TimeoutSec 1 | Out-Null
            $backendReady = $true
            break
        } catch {
            Start-Sleep -Milliseconds 300
        }
    }
    if (-not $backendReady) {
        throw "O backend nao respondeu na porta 8080."
    }

    Write-Host "PersonOfInterest V2 online: http://localhost:8080" -ForegroundColor Green
    Write-Host "Pressione Ctrl+C para encerrar." -ForegroundColor DarkGray
    if (-not $NoBrowser) {
        Start-Process "http://localhost:8080"
    }

    while (-not $Backend.HasExited) {
        Start-Sleep -Seconds 1
    }
} finally {
    Write-Host "Encerrando PersonOfInterest..." -ForegroundColor DarkGray
    if ($Backend -and -not $Backend.HasExited) {
        Stop-Process -Id $Backend.Id -Force -ErrorAction SilentlyContinue
    }
    if ($Go2rtc -and -not $Go2rtc.HasExited) {
        Stop-Process -Id $Go2rtc.Id -Force -ErrorAction SilentlyContinue
    }
}
