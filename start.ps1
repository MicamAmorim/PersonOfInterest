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
$ModelsDir = Join-Path $Root "data\models"
$VisionModel = Join-Path $ModelsDir "yolox_tiny.onnx"
$FaceDetectorModel = Join-Path $ModelsDir "face_detection_yunet_2023mar.onnx"
$FaceRecognizerModel = Join-Path $ModelsDir "face_recognition_sface_2021dec.onnx"
$BodyReidModel = Join-Path $ModelsDir "osnet_x0_25_msmt17.onnx"

$VisionModelUrl = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx"
$FaceDetectorModelUrl = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
$FaceRecognizerModelUrl = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
$BodyReidModelUrl = "https://huggingface.co/anriha/osnet_x0_25_msmt17/resolve/main/osnet_x0_25_msmt17.onnx?download=true"

if (-not (Test-Path $PythonExe) -or -not (Test-Path $Go2rtcExe)) {
    throw "Instalacao incompleta. Execute .\setup.ps1 primeiro."
}

Write-Host "Verificando dependencias da V4.5..." -ForegroundColor DarkGray
$oldErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $PythonExe -c "import cv2,numpy,onnxruntime,websockets,pywebpush,cryptography,edge_tts,faster_whisper,av,sys; from zoneinfo import ZoneInfo; ZoneInfo('America/Sao_Paulo'); ok=int(cv2.__version__.split('.')[0])<5 and hasattr(cv2,'FaceDetectorYN_create') and hasattr(cv2,'FaceRecognizerSF_create'); sys.exit(0 if ok else 2)" *> $null
    $depsExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $oldErrorActionPreference
}

if ($depsExitCode -ne 0) {
    Write-Host "Ajustando dependencias de visao, identidade, assistente, voz local, fusos horarios e Web Push..." -ForegroundColor Yellow
    & $PythonExe -m pip install --upgrade -r $Requirements
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao instalar as dependencias da V4.5."
    }
}

& $PythonExe -c "import cv2,numpy,onnxruntime,pywebpush,cryptography,edge_tts,faster_whisper,av; from zoneinfo import ZoneInfo; ZoneInfo('America/Sao_Paulo'); assert int(cv2.__version__.split('.')[0]) < 5; assert hasattr(cv2,'FaceDetectorYN_create'); assert hasattr(cv2,'FaceRecognizerSF_create'); print('OpenCV',cv2.__version__,'| NumPy',numpy.__version__,'| ONNX Runtime',onnxruntime.__version__,'| Edge TTS OK | faster-whisper OK | Timezone DB OK | Web Push OK')"
if ($LASTEXITCODE -ne 0) {
    throw "Dependencias da V4.5 nao estao compativeis."
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "data") | Out-Null
New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null

function Ensure-Model([string]$Path, [string]$Url, [long]$MinimumBytes, [string]$Label) {
    if ((Test-Path $Path) -and (Get-Item $Path).Length -ge $MinimumBytes) { return }
    Write-Host "Baixando $Label (uma unica vez)..." -ForegroundColor Yellow
    $Part = "$Path.part"
    if (Test-Path $Part) { Remove-Item $Part -Force }
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Part -UseBasicParsing
        if ((Get-Item $Part).Length -lt $MinimumBytes) {
            throw "Arquivo de modelo incompleto."
        }
        Move-Item $Part $Path -Force
    } catch {
        if (Test-Path $Part) { Remove-Item $Part -Force }
        throw "Falha ao baixar ${Label}: $($_.Exception.Message)"
    }
}

Ensure-Model $VisionModel $VisionModelUrl 1000000 "YOLOX-Tiny ONNX"
Ensure-Model $FaceDetectorModel $FaceDetectorModelUrl 150000 "YuNet face detector"
Ensure-Model $FaceRecognizerModel $FaceRecognizerModelUrl 10000000 "SFace face embedding"
Ensure-Model $BodyReidModel $BodyReidModelUrl 700000 "OSNet x0.25 body ReID"

$env:DATA_DIR = Join-Path $Root "data"
$env:FRONTEND_DIR = Join-Path $Root "frontend"
$env:GO2RTC_API_URL = "http://127.0.0.1:1984"
$env:GO2RTC_BROWSER_BASE = "direct"
$env:VISION_MODEL_PATH = $VisionModel
$env:FACE_DETECTOR_MODEL_PATH = $FaceDetectorModel
$env:FACE_RECOGNIZER_MODEL_PATH = $FaceRecognizerModel
$env:BODY_REID_MODEL_PATH = $BodyReidModel

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

Write-Host "=== PersonOfInterest V4.5 ===" -ForegroundColor Cyan
Write-Host "Iniciando go2rtc..."
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

    Write-Host "Iniciando API, identidade facial/corporal, assistente Tonho, alertas, timeline e visao em http://localhost:8080 ..."
    $Backend = Start-Process -FilePath $PythonExe -ArgumentList @(
        "-m", "uvicorn", "app.main:app",
        "--app-dir", "backend",
        "--host", "0.0.0.0",
        "--port", "8080"
    ) -WorkingDirectory $Root -PassThru -NoNewWindow

    $backendReady = $false
    for ($i = 0; $i -lt 90; $i++) {
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

    Write-Host "PersonOfInterest V4.5 online: http://localhost:8080" -ForegroundColor Green
    Write-Host "Para acesso seguro no celular: .\tailscale-serve.ps1" -ForegroundColor DarkGray
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
