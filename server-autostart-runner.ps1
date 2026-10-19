param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$LogDir = Join-Path $Root "data\logs"
$LogPath = Join-Path $LogDir "server-autostart.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-AutostartLog([string]$Message) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogPath -Value "[$stamp] $Message" -Encoding UTF8
}

function Test-PersonOfInterestHealth {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/health" -TimeoutSec 2
        return ($health.app -eq "PersonOfInterest")
    } catch {
        return $false
    }
}

if (Test-PersonOfInterestHealth) {
    Write-AutostartLog "Servidor já estava online; nenhuma segunda instância foi iniciada."
    exit 0
}

$StartScript = Join-Path $Root "start.ps1"
if (-not (Test-Path $StartScript)) {
    Write-AutostartLog "ERRO: start.ps1 não encontrado em $Root"
    exit 2
}

Write-AutostartLog "Iniciando PersonOfInterest em modo servidor (-NoBrowser)."
try {
    & $StartScript -NoBrowser *>> $LogPath
    $exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
    Write-AutostartLog "start.ps1 encerrou com código $exitCode."
    # A tarefa agendada está configurada para reiniciar em caso de falha. Se o
    # servidor encerrou sozinho, tratamos isso como falha para permitir recovery.
    if ($exitCode -eq 0) { exit 1 }
    exit $exitCode
} catch {
    Write-AutostartLog "ERRO: $($_.Exception.Message)"
    exit 1
}
