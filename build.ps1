<#
.SYNOPSIS
    Garmin Sleep Reporter のリリースビルドを1コマンドで行う。

.DESCRIPTION
    ① PyInstaller で GUI exe（dist\GarminSleepReporter\）を生成し、
    ② Inno Setup(ISCC) で配布用 Setup.exe（Output\GarminSleepReporter-Setup.exe）を生成する。
    ISCC は dist\ を箱詰めするだけなので、コードを変えたら必ず①→②の順で実行する必要がある。
    本スクリプトはその2段を順に実行し、途中で失敗したら止める。

.PARAMETER Clean
    実行前に build\ dist\ Output\ を削除してクリーンビルドする。

.PARAMETER Version
    指定すると installer.iss の AppVersion をこの値に書き換えてからビルドする（例: 1.0.1）。
    未指定なら現状の版のまま。AppId は変更しない。

.EXAMPLE
    ./build.ps1
    ./build.ps1 -Clean
    ./build.ps1 -Version 1.0.1
#>
[CmdletBinding()]
param(
    [switch]$Clean,
    [string]$Version
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Write-Step($msg)  { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host $msg -ForegroundColor Green }
function Write-Fail($msg)  { Write-Host $msg -ForegroundColor Red }

# --- 任意: バージョン更新（installer.iss の AppVersion 行のみ書き換え）---
if ($Version) {
    if ($Version -notmatch '^\d+\.\d+\.\d+$') {
        Write-Fail "Version は x.y.z 形式で指定してください（例: 1.0.1）。指定値: $Version"
        exit 1
    }
    Write-Step "installer.iss の AppVersion を $Version に更新"
    $iss = "installer.iss"
    $content = Get-Content $iss -Raw -Encoding UTF8
    $updated = [regex]::Replace(
        $content,
        '(#define\s+AppVersion\s+")[^"]*(")',
        "`${1}$Version`${2}"
    )
    if ($updated -eq $content) {
        Write-Fail "AppVersion 行が見つからず更新できませんでした。installer.iss を確認してください。"
        exit 1
    }
    Set-Content -Path $iss -Value $updated -Encoding UTF8 -NoNewline
    Write-Ok "AppVersion を $Version に更新しました。"
}

# --- 任意: クリーンビルド ---
if ($Clean) {
    Write-Step "クリーンアップ（build / dist / Output）"
    foreach ($d in @("build", "dist", "Output")) {
        if (Test-Path $d) { Remove-Item $d -Recurse -Force }
    }
    Write-Ok "削除しました。"
}

# --- Step 1: PyInstaller ---
Write-Step "Step 1/2: PyInstaller で exe をビルド"
python -m PyInstaller garminsleep.spec --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Fail "PyInstaller のビルドに失敗しました。"
    Write-Host "  未導入なら: pip install pyinstaller" -ForegroundColor Yellow
    exit 1
}
$exePath = Join-Path $PSScriptRoot "dist\GarminSleepReporter\GarminSleepReporter.exe"
if (-not (Test-Path $exePath)) {
    Write-Fail "ビルドは完了しましたが exe が見つかりません: $exePath"
    exit 1
}
Write-Ok "exe を生成: $exePath"

# --- Step 2: Inno Setup(ISCC) を探して実行 ---
Write-Step "Step 2/2: Inno Setup で Setup.exe を作成"
$iscc = $null
$cmd = Get-Command iscc -ErrorAction SilentlyContinue
if ($cmd) {
    $iscc = $cmd.Source
} else {
    foreach ($p in @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )) {
        if (Test-Path $p) { $iscc = $p; break }
    }
}

if (-not $iscc) {
    Write-Fail "Inno Setup (ISCC.exe) が見つかりませんでした。"
    Write-Host "  ダウンロード: https://jrsoftware.org/isdl.php" -ForegroundColor Yellow
    Write-Host "  インストール後にもう一度 ./build.ps1 を実行してください。" -ForegroundColor Yellow
    Write-Host "  （PyInstaller の成果物 dist\ は生成済みです）" -ForegroundColor Yellow
    exit 1
}

& $iscc "installer.iss"
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Inno Setup のコンパイルに失敗しました。"
    exit 1
}

$setup = Join-Path $PSScriptRoot "Output\GarminSleepReporter-Setup.exe"
Write-Step "ビルド完了"
if (Test-Path $setup) {
    Write-Ok "配布用インストーラ: $setup"
} else {
    Write-Ok "Inno Setup は成功しました（出力先は installer.iss の OutputDir を参照）。"
}
