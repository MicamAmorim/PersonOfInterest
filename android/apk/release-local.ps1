#requires -version 5.1
param(
    [Parameter(Mandatory)][string]$Gradle,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$Sdk,
    [Parameter(Mandatory)][string]$Keystore,
    [Parameter(Mandatory)][string]$PasswordFile,
    [string]$BuildTools = '36.0.0',
    [string]$KeyAlias = 'poi-android',
    [switch]$Publish,
    [string]$Repository = 'MicamAmorim/PersonOfInterest',
    [string]$Tag = 'android-server-v0.1.1',
    [string]$FfmpegSource
)

$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$env:ANDROID_HOME = (Resolve-Path $Sdk).Path
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$Gradle = (Resolve-Path $Gradle).Path
$Python = (Resolve-Path $Python).Path
$Keystore = (Resolve-Path $Keystore).Path
$PasswordFile = (Resolve-Path $PasswordFile).Path

function Assert-Exit([string]$Name) {
    if ($LASTEXITCODE -ne 0) { throw "$Name falhou com código $LASTEXITCODE." }
}

foreach ($arch in @('armeabi-v7a', 'arm64-v8a')) {
    foreach ($name in @('ffmpeg', 'go2rtc', 'vpn')) {
        $library = Join-Path $PSScriptRoot "app/build/generated/poiNative/$arch/libpoi_$name.so"
        if (!(Test-Path -LiteralPath $library)) { throw "Compile os binários em native/build.sh antes do APK. Ausente $library" }
    }
}

& $Gradle -p $PSScriptRoot ':app:assembleRelease' --no-daemon "-PpoiBuildPython=$Python"
Assert-Exit 'Gradle'
$unsigned = Join-Path $PSScriptRoot 'app/build/outputs/apk/release/app-release-unsigned.apk'
$tools = Join-Path $env:ANDROID_HOME "build-tools\$BuildTools"
$zipalign = Join-Path $tools 'zipalign.exe'
$signer = Join-Path $tools 'apksigner.bat'
$dist = (New-Item -ItemType Directory -Force (Join-Path $project 'dist')).FullName
$aligned = Join-Path $dist 'poi-aligned-unsigned.apk'
$asset = Join-Path $dist 'POI-Server-Android.apk'
& $zipalign -f -P 16 4 $unsigned $aligned
Assert-Exit 'zipalign'
& $signer sign --ks $Keystore --ks-key-alias $KeyAlias --ks-pass "file:$PasswordFile" --out $asset $aligned
Assert-Exit 'Assinatura do APK'
& $signer verify --verbose --print-certs $asset
Assert-Exit 'Verificação da assinatura'
& $zipalign -c -P 16 4 $asset
Assert-Exit 'Verificação do alinhamento'
$shaFile = Join-Path $dist 'POI-Server-Android.apk.sha256'
$sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $asset).Hash.ToLowerInvariant()
"$sha  POI-Server-Android.apk" | Set-Content -Encoding ascii -LiteralPath $shaFile
Write-Output $asset
if (!$Publish) { exit 0 }

if (!$FfmpegSource) { throw 'Informe o código-fonte correspondente do FFmpeg com -FfmpegSource.' }
$FfmpegSource = (Resolve-Path $FfmpegSource).Path
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $FfmpegSource).Hash -ine '1a4d394ae63d190a526cd052eb4415c156b5c5e2df37efab41a7de0b8fde2433') {
    throw 'O arquivo fonte do FFmpeg difere da versão usada no APK.'
}
if (@(& git -C $project status --porcelain).Count) { throw 'Salve as alterações em um commit antes de publicar.' }
$commit = (& git -C $project rev-parse HEAD).Trim()
Assert-Exit 'Leitura do commit'
& gh api "repos/$Repository/commits/$commit" --jq .sha | Out-Null
Assert-Exit 'Confirmação do commit publicado'
& gh release create $Tag $asset $shaFile "$FfmpegSource#FFmpeg 9.1 corresponding source" --repo $Repository --target $commit --title 'POI Server para Android 0.1.1' --notes-file (Join-Path $PSScriptRoot 'release-notes.md') --prerelease
Assert-Exit 'Publicação no GitHub Releases'
