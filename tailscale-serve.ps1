param(
    [switch]$Off,
    [switch]$Status
)

$ErrorActionPreference = "Stop"

$Tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $Tailscale) {
    throw "Tailscale CLI nao encontrado. Instale/abra o Tailscale e tente novamente."
}

if ($Status) {
    & tailscale serve status
    exit $LASTEXITCODE
}

if ($Off) {
    Write-Host "Desativando Tailscale Serve..." -ForegroundColor Yellow
    & tailscale serve reset
    exit $LASTEXITCODE
}

Write-Host "Publicando PersonOfInterest somente dentro da sua tailnet..." -ForegroundColor Cyan
Write-Host "O backend local deve estar rodando em http://localhost:8080." -ForegroundColor DarkGray

# Current Tailscale Serve syntax: HTTPS is the default and the target may be
# localhost:<port>. --bg keeps the reverse proxy active in the background.
& tailscale serve --bg localhost:8080
if ($LASTEXITCODE -ne 0) {
    throw "Nao foi possivel configurar Tailscale Serve. Execute 'tailscale serve --help' para detalhes."
}

Write-Host "" 
& tailscale serve status
Write-Host "" 
Write-Host "Abra a URL https://...ts.net exibida acima no celular." -ForegroundColor Green
Write-Host "Ela e um contexto HTTPS valido para PWA, Web Push e microfone do navegador." -ForegroundColor DarkGray
