param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "Este script é exclusivo do Windows."
}

$TaskName = "PersonOfInterest Server"

if (-not (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue)) {
    throw "O módulo ScheduledTasks do Windows não está disponível neste sistema."
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "Nenhuma tarefa de autostart do PersonOfInterest estava instalada." -ForegroundColor Yellow
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Autostart do PersonOfInterest removido." -ForegroundColor Green
Write-Host "O servidor que já estiver rodando não é encerrado por este comando." -ForegroundColor DarkGray
Write-Host "A partir do próximo logon ele não será iniciado automaticamente." -ForegroundColor DarkGray
