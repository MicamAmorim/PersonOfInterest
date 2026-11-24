#requires -version 5.1
# Local build and GitHub Release without GitHub Actions.
# This is a Termux controller beta, not an independent native Android server.
param([switch]$BuildOnly, [string]$Repo = "MicamAmorim/PersonOfInterest")
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$cache = Join-Path $PSScriptRoot ".toolchain"
$dl = Join-Path $cache "downloads"
New-Item -ItemType Directory -Force -Path $cache,$dl | Out-Null

function Assert-Exit([string]$name) {
  if ($LASTEXITCODE -ne 0) { throw "$name falhou (codigo $LASTEXITCODE)." }
}
function Download-Verified([string]$url, [string]$path, [string]$sha256) {
  if (!(Test-Path $path) -or (Get-FileHash -Algorithm SHA256 $path).Hash -ine $sha256) {
    Write-Host "Baixando $url"
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $path
  }
  if ((Get-FileHash -Algorithm SHA256 $path).Hash -ine $sha256) {
    Remove-Item -Force $path
    throw "Checksum incorreto: $url"
  }
}

# Portable Temurin JDK 21 with checksum validation.
$jdkDir = Join-Path $cache "jdk"
$java = Get-ChildItem -Path $jdkDir -Filter java.exe -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.DirectoryName -like "*\bin" } | Select-Object -First 1
if ($null -eq $java) {
  $metadata = @(Invoke-RestMethod -Uri "https://api.adoptium.net/v3/assets/latest/21/hotspot?architecture=x64&image_type=jdk&os=windows")
  if ($metadata.Count -eq 0) { throw "Temurin 21 nao encontrado." }
  $package = $metadata[0].binary.package
  $file = Join-Path $dl "temurin-jdk21.zip"
  Download-Verified $package.link $file $package.checksum
  New-Item -ItemType Directory -Force $jdkDir | Out-Null
  Expand-Archive -Path $file -DestinationPath $jdkDir -Force
  $java = Get-ChildItem -Path $jdkDir -Filter java.exe -File -Recurse | Where-Object { $_.DirectoryName -like "*\bin" } | Select-Object -First 1
}
if ($null -eq $java) { throw "java.exe nao encontrado." }
$env:JAVA_HOME = Split-Path $java.DirectoryName -Parent
$env:Path = (Join-Path $env:JAVA_HOME "bin") + ";" + $env:Path

# Official Google Android command-line tools and SDK packages.
$sdk = Join-Path $cache "android-sdk"
$manager = Join-Path $sdk "cmdline-tools\latest\bin\sdkmanager.bat"
if (!(Test-Path $manager)) {
  $file = Join-Path $dl "android-cmdline.zip"
  Download-Verified "https://dl.google.com/android/repository/commandlinetools-win-15859902_latest.zip" $file "90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a"
  $unpack = Join-Path $cache "sdk-unpacked"
  if (Test-Path $unpack) { Remove-Item -Force -Recurse $unpack }
  Expand-Archive -Path $file -DestinationPath $unpack
  $parent = Join-Path $sdk "cmdline-tools"
  New-Item -ItemType Directory -Force $parent | Out-Null
  Move-Item (Join-Path $unpack "cmdline-tools") (Join-Path $parent "latest")
  Remove-Item -Force -Recurse $unpack
}
$env:ANDROID_HOME = $sdk
$env:ANDROID_SDK_ROOT = $sdk
if (!(Test-Path (Join-Path $sdk "platforms\android-35\android.jar")) -or !(Test-Path (Join-Path $sdk "build-tools\35.0.0\apksigner.bat"))) {
  Write-Host "Leia e aceite as licencas do Android SDK quando solicitadas."
  & $manager "--sdk_root=$sdk" --licenses
  Assert-Exit "Licencas do SDK"
  & $manager "--sdk_root=$sdk" "platforms;android-35" "build-tools;35.0.0" "platform-tools"
  Assert-Exit "Instalacao do SDK Android"
}

# Gradle 8.9: download and check published SHA256.
$gradle = Join-Path $cache "gradle-8.9\bin\gradle.bat"
if (!(Test-Path $gradle)) {
  $url = "https://services.gradle.org/distributions/gradle-8.9-bin.zip"
  $checksum = ((Invoke-WebRequest -UseBasicParsing -Uri "$url.sha256").Content.Trim() -split "\s+")[0]
  if ($checksum -notmatch "^[a-fA-F0-9]{64}$") { throw "SHA256 do Gradle indisponivel." }
  $file = Join-Path $dl "gradle-8.9-bin.zip"
  Download-Verified $url $file $checksum
  Expand-Archive -Path $file -DestinationPath $cache -Force
}
Write-Host "Compilando APK (sem GitHub Actions)..."
& $gradle "-p" $PSScriptRoot ":app:assembleDebug" "--no-daemon"
Assert-Exit "Gradle"
$apk = Join-Path $PSScriptRoot "app\build\outputs\apk\debug\app-debug.apk"
if (!(Test-Path $apk)) { throw "APK nao encontrado no destino do Gradle." }
$signer = Join-Path $sdk "build-tools\35.0.0\apksigner.bat"
& $signer verify --verbose --print-certs $apk
Assert-Exit "Verificacao da assinatura"
$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Force $dist | Out-Null
$asset = Join-Path $dist "POI-Server-Android-Controller-beta.apk"
Copy-Item -Force $apk $asset
$sha = (Get-FileHash -Algorithm SHA256 $asset).Hash
Write-Host "APK compilado: $asset"
Write-Host "SHA256: $sha"
if ($BuildOnly) { Write-Host "BuildOnly: Release nao criada."; exit 0 }

# gh (authenticated on this PC) uploads the binary directly; Actions are never used.
$gh = Get-Command gh -ErrorAction SilentlyContinue
$ghExe = if ($null -ne $gh) { $gh.Source } else { Join-Path $env:ProgramFiles "GitHub CLI\gh.exe" }
if (!(Test-Path $ghExe)) {
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if ($null -ne $winget) {
    Write-Host "Instalando GitHub CLI sem depender de Actions..."
    & $winget.Source install --id GitHub.cli --exact --source winget --accept-package-agreements --accept-source-agreements
    Assert-Exit "Instalacao de GitHub CLI"
    $foundGh = Get-Command gh -ErrorAction SilentlyContinue
    if ($null -ne $foundGh) { $ghExe = $foundGh.Source }
    elseif (Test-Path (Join-Path $env:ProgramFiles "GitHub CLI\gh.exe")) { $ghExe = Join-Path $env:ProgramFiles "GitHub CLI\gh.exe" }
    elseif (Test-Path (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\gh.exe")) { $ghExe = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\gh.exe" }
  }
}
if (!(Test-Path $ghExe)) {
  throw "GitHub CLI indisponivel. Instale em https://cli.github.com/ e execute novamente. O APK foi compilado em $asset"
}
& $ghExe auth status --hostname github.com
if ($LASTEXITCODE -ne 0) {
  Write-Host "Autenticando GitHub pelo navegador..."
  & $ghExe auth login --hostname github.com --web
  Assert-Exit "Autenticacao no GitHub"
}
$commit = (& git -C $root rev-parse HEAD)
Assert-Exit "Git HEAD"
$short = $commit.Substring(0,7)
$tag = "android-controller-beta-$short"
$assetWithName = "$asset#POI-Server-Android-Controller-beta.apk"
& $ghExe release view $tag --repo $Repo *> $null
if ($LASTEXITCODE -eq 0) {
  & $ghExe release upload $tag $assetWithName --repo $Repo --clobber
  Assert-Exit "Upload da Release"
} else {
  & $ghExe release create $tag $assetWithName --repo $Repo --target $commit --title "POI Server Android Controller beta ($short)" --prerelease --notes "Beta experimental: controla o servidor Android Lite existente em Termux/Debian. Nao e um servidor autonomo. Requer permissao RUN_COMMAND, configuracao de bateria e testes no Redmi 9. APK com assinatura debug."
  Assert-Exit "Criacao da Release"
}
Write-Host "Release publicada:"
& $ghExe release view $tag --repo $Repo --json url --jq ".url"
Assert-Exit "Verificacao da Release"
