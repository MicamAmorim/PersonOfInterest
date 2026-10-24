param(
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "Este instalador de autostart é exclusivo do Windows."
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$TaskName = "PersonOfInterest Server"
$Runner = Join-Path $Root "server-autostart-runner.ps1"
$StartScript = Join-Path $Root "start.ps1"

if (-not (Test-Path $Runner)) {
    throw "server-autostart-runner.ps1 não encontrado. Atualize o repositório e tente novamente."
}
if (-not (Test-Path $StartScript)) {
    throw "start.ps1 não encontrado."
}

if (-not (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)) {
    throw "O módulo ScheduledTasks do Windows não está disponível neste sistema."
}

$WindowsPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$PowerShellExe = if (Test-Path $WindowsPowerShell) { $WindowsPowerShell } else { (Get-Command powershell.exe -ErrorAction Stop).Source }
$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$Arguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Runner`""
$Action = New-ScheduledTaskAction -Execute $PowerShellExe -Argument $Arguments -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser
$Principal = New-ScheduledTaskPrincipal -UserId $CurrentUser -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings `
    -Description "Inicia o servidor local PersonOfInterest no logon do usuário, sem abrir o navegador."

Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null

Write-Host ""
Write-Host "Autostart do PersonOfInterest instalado." -ForegroundColor Green
Write-Host "Tarefa: $TaskName"
Write-Host "Usuário: $CurrentUser"
Write-Host "Projeto: $Root"
Write-Host "Modo: start.ps1 -NoBrowser"
Write-Host "Log: $(Join-Path $Root 'data\logs\server-autostart.log')"

if (-not $NoStart) {
    try {
        Start-ScheduledTask -TaskName $TaskName
        Write-Host "Servidor solicitado agora em segundo plano." -ForegroundColor Green
        Write-Host "Aguarde alguns segundos e abra http://localhost:8080"
    } catch {
        Write-Warning "A tarefa foi instalada, mas não pôde ser iniciada agora: $($_.Exception.Message)"
        Write-Host "Ela será executada automaticamente no próximo logon."
    }
} else {
    Write-Host "A tarefa será executada automaticamente no próximo logon."
}

Write-Host ""
Write-Host "Para remover depois: .\remove-server-autostart.ps1" -ForegroundColor DarkGray
