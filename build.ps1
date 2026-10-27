# Builds the Windows installer: offline tests, PyInstaller (onedir, windowed), Inno Setup -> dist\MusicTransfer-Setup-<version>.exe
# Run from anywhere: powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot  # PyInstaller must run here: this folder has no __init__.py (Qt DLL loading breaks otherwise)
$py = '.venv\Scripts\python.exe'
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Нет Inno Setup 6: winget install --id JRSoftware.InnoSetup -e --scope user' }

Write-Host '=== Тесты без сети ==='
$env:HTTPS_PROXY = 'http://127.0.0.1:9'
& $py -m pytest -q
$code = $LASTEXITCODE
Remove-Item Env:HTTPS_PROXY
if ($code -ne 0) { throw 'Тесты не прошли, сборки не будет' }

Write-Host '=== PyInstaller ==='
# onedir, not onefile: antivirus flags self-extracting exes more often; the installer makes it one file anyway
& $py -m PyInstaller --noconfirm --clean --onedir --windowed --name MusicTransfer `
    --specpath build --add-data "$PSScriptRoot\music_transfer\assets;music_transfer/assets" `
    --python-option 'X utf8' main.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller не собрал программу' }

Write-Host '=== Inno Setup ==='
$version = (Select-String music_transfer\__init__.py -Pattern '__version__ = "([\d.]+)"').Matches[0].Groups[1].Value
& $iscc /Q "/DAppVersion=$version" installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup не собрал установщик' }
Get-ChildItem dist\MusicTransfer-Setup-*.exe | Select-Object Name, @{n='MB'; e={[math]::Round($_.Length / 1MB, 1)}}
