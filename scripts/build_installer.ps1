<#
.SYNOPSIS
    Gera o instalador Windows do INTARQ AI Assistant.

.DESCRIPTION
    Encadeia as quatro etapas na ordem que importa:

      1. testes da interface  - a guarda de assets/config/app_defaults.json
                                reprova aqui, antes de virar release;
      2. flutter build        - gera o Release;
      3. verificacao do bundle - confirma que o asset de configuracao entrou de
                                fato em flutter_assets. O Flutter nao reclama de
                                pasta de asset declarada e vazia, e um build sem
                                esse arquivo aponta todos os usuarios para
                                localhost;
      4. Inno Setup           - compila o .exe do instalador.

    A etapa 3 existe por causa de um incidente real: o arquivo sumiu, o build
    passou, e o app instalado nao conectava.

.PARAMETER SkipTests
    Pula a suite da interface. Use so para reempacotar um build ja validado.

.PARAMETER SkipBuild
    Reaproveita o Release existente em vez de reconstruir.

.PARAMETER Version
    Sobrescreve a versao. Por padrao vem do pubspec.yaml.

.EXAMPLE
    pwsh scripts/build_installer.ps1

.EXAMPLE
    pwsh scripts/build_installer.ps1 -SkipBuild -Version 1.1.0
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipBuild,
    [string]$Version
)

$ErrorActionPreference = 'Stop'

$repoRoot     = Split-Path -Parent $PSScriptRoot
$interfaceDir = Join-Path $repoRoot 'interface'
$issFile      = Join-Path $repoRoot 'installer\intarq.iss'
$releaseDir   = Join-Path $interfaceDir 'build\windows\x64\runner\Release'
$distDir      = Join-Path $repoRoot 'dist'
$assetInBundle = 'data\flutter_assets\assets\config\app_defaults.json'

function Write-Step([string]$text) {
    Write-Host ''
    Write-Host "==> $text" -ForegroundColor Cyan
}

function Resolve-Iscc {
    <#  ISCC nao entra no PATH por padrao, entao procuramos onde o instalador
        do Inno Setup costuma deixar antes de desistir. #>
    $candidates = @(
        'ISCC.exe',
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found) { return $found.Source }
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Get-PubspecVersion {
    $pubspec = Get-Content (Join-Path $interfaceDir 'pubspec.yaml') -Raw
    if ($pubspec -match '(?m)^version:\s*([0-9]+\.[0-9]+\.[0-9]+)') {
        return $Matches[1]
    }
    throw 'Nao consegui ler a versao do pubspec.yaml.'
}

# --- versao -----------------------------------------------------------------

if (-not $Version) { $Version = Get-PubspecVersion }
Write-Host "INTARQ AI Assistant $Version" -ForegroundColor Green

# --- 1. testes --------------------------------------------------------------

if ($SkipTests) {
    Write-Step 'Testes da interface: PULADOS (-SkipTests)'
} else {
    Write-Step 'Testes da interface'
    Push-Location $interfaceDir
    try {
        flutter test
        if ($LASTEXITCODE -ne 0) {
            throw "Testes reprovaram. Se a falha for em app_defaults_asset_test, " +
                  "o arquivo interface/assets/config/app_defaults.json esta " +
                  "ausente ou invalido - empacotar assim geraria um instalador " +
                  "que aponta para localhost."
        }
    } finally { Pop-Location }
}

# --- 2. build ---------------------------------------------------------------

if ($SkipBuild) {
    Write-Step 'Build do Flutter: PULADO (-SkipBuild)'
    if (-not (Test-Path (Join-Path $releaseDir 'assistant_app.exe'))) {
        throw "Nao existe Release em $releaseDir. Rode sem -SkipBuild."
    }
} else {
    Write-Step 'Build do Flutter (release)'
    Push-Location $interfaceDir
    try {
        flutter build windows --release
        if ($LASTEXITCODE -ne 0) { throw 'flutter build windows falhou.' }
    } finally { Pop-Location }
}

# --- 3. verificacao do bundle ----------------------------------------------

Write-Step 'Verificando o conteudo do bundle'

$assetPath = Join-Path $releaseDir $assetInBundle
if (-not (Test-Path $assetPath)) {
    throw "O bundle saiu sem $assetInBundle. " +
          "O app instalado cairia para http://localhost:8000 em todas as " +
          "maquinas. Rode 'flutter clean' e construa de novo."
}

$defaults = Get-Content $assetPath -Raw | ConvertFrom-Json
if (-not $defaults.backendUrl) {
    throw 'app_defaults.json no bundle esta sem backendUrl.'
}
if ($defaults.environment -eq 'production' -and
    $defaults.backendUrl -match 'localhost|127\.0\.0\.1') {
    throw "app_defaults.json diz environment=production mas aponta para " +
          "$($defaults.backendUrl). Isso empacotaria um instalador inutil " +
          "para qualquer usuario que nao seja voce."
}

Write-Host "    backendUrl : $($defaults.backendUrl)"
Write-Host "    environment: $($defaults.environment)"

$payloadMb = [math]::Round(
    ((Get-ChildItem $releaseDir -Recurse -File |
      Measure-Object -Property Length -Sum).Sum / 1MB), 1)
Write-Host "    payload    : $payloadMb MB"

# --- 4. Inno Setup ----------------------------------------------------------

Write-Step 'Compilando o instalador'

$iscc = Resolve-Iscc
if (-not $iscc) {
    Write-Host ''
    Write-Host 'Inno Setup nao encontrado.' -ForegroundColor Yellow
    Write-Host 'Instale uma vez com:' -ForegroundColor Yellow
    Write-Host '    winget install --id JRSoftware.InnoSetup -e' -ForegroundColor Yellow
    Write-Host 'e rode este script de novo.' -ForegroundColor Yellow
    exit 1
}
Write-Host "    ISCC: $iscc"

New-Item -ItemType Directory -Force -Path $distDir | Out-Null

& $iscc `
    "/DAppVersion=$Version" `
    "/DSourceDir=$releaseDir" `
    "/DOutputDir=$distDir" `
    "/DIconFile=$(Join-Path $interfaceDir 'windows\runner\resources\app_icon.ico')" `
    "/DLicenseFile=$(Join-Path $repoRoot 'LICENSE')" `
    $issFile

if ($LASTEXITCODE -ne 0) { throw 'ISCC falhou ao compilar o instalador.' }

$setup = Join-Path $distDir "INTARQ-Setup-$Version.exe"
$setupMb = [math]::Round((Get-Item $setup).Length / 1MB, 1)

Write-Host ''
Write-Host "Instalador pronto: $setup ($setupMb MB)" -ForegroundColor Green
Write-Host ''
Write-Host 'Sem assinatura de codigo, o SmartScreen mostra um aviso na primeira' -ForegroundColor DarkGray
Write-Host 'execucao. Some com um certificado de code signing (EV remove logo;' -ForegroundColor DarkGray
Write-Host 'OV precisa acumular reputacao).' -ForegroundColor DarkGray
