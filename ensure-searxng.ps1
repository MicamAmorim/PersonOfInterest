$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Url = "http://127.0.0.1:8888"

function Test-Searxng {
    try {
        $probe = Invoke-RestMethod -Uri "$Url/search?q=teste&format=json&language=pt-BR&categories=general" -Method Get -TimeoutSec 4
        return ($null -ne $probe -and $null -ne $probe.results)
    } catch {
        return $false
    }
}

if (Test-Searxng) {
    Write-Host "SearXNG local pronto em $Url" -ForegroundColor DarkGreen
    Write-Output $Url
    exit 0
}

$Docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $Docker) {
    Write-Host "SearXNG local: Docker nao encontrado; Tonho usara o fallback gratuito." -ForegroundColor DarkYellow
    Write-Output ""
    exit 0
}

$oldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & docker info *> $null
    $dockerReady = $LASTEXITCODE -eq 0
} finally {
    $ErrorActionPreference = $oldPreference
}

if (-not $dockerReady) {
    Write-Host "SearXNG local: Docker esta instalado, mas nao esta ativo; Tonho usara o fallback gratuito." -ForegroundColor DarkYellow
    Write-Output ""
    exit 0
}

Write-Host "Iniciando SearXNG local para as pesquisas do Tonho..." -ForegroundColor DarkCyan
$oldPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & docker compose -f (Join-Path $Root "docker-compose.yml") up -d searxng *> $null
    $composeOk = $LASTEXITCODE -eq 0
} finally {
    $ErrorActionPreference = $oldPreference
}

if ($composeOk) {
    for ($i = 0; $i -lt 75; $i++) {
        if (Test-Searxng) {
            Write-Host "SearXNG local pronto em $Url" -ForegroundColor DarkGreen
            Write-Output $Url
            exit 0
        }
        Start-Sleep -Milliseconds 400
    }
}

Write-Host "SearXNG local nao passou no teste de pesquisa; Tonho usara o fallback gratuito nesta execucao." -ForegroundColor DarkYellow
Write-Output ""
