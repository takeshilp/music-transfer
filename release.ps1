# Publishes version __version__ (music_transfer\__init__.py): the installer via build.ps1, the public GitHub repository
# if it does not exist yet, a push of the current branch and tag v<version>, a GitHub release with the setup.exe.
# Once: gh auth login. For each new version: raise __version__, commit, then
#   powershell -ExecutionPolicy Bypass -File release.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$version = (Select-String music_transfer\__init__.py -Pattern '__version__ = "([\d.]+)"').Matches[0].Groups[1].Value
$repo = (Select-String music_transfer\update.py -Pattern 'REPO = "([^"]+)"').Matches[0].Groups[1].Value
$tag = "v$version"

$login = gh api user --jq .login
if ($LASTEXITCODE -ne 0) { throw 'Сначала войдите в GitHub: gh auth login' }
if ($repo -notlike "$login/*") { throw "Программа ищет обновления в $repo, а вы вошли как $login. Поправьте REPO в music_transfer\update.py и закоммитьте." }
if (git status --porcelain) { throw 'Есть незакоммиченные изменения: сначала закоммитьте их' }
if (git tag --list $tag) { throw "Версия $version уже выпущена: поднимите __version__ в music_transfer\__init__.py" }

& .\build.ps1

cmd /c "gh repo view $repo >nul 2>nul"  # through cmd: PowerShell 5.1 turns redirected stderr into a terminating error
if ($LASTEXITCODE -ne 0) {
    gh repo create $repo --public --source . --remote origin --description 'Перенос плейлистов между Spotify и Яндекс Музыкой (Windows)'
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать репозиторий на GitHub' }
}
git tag $tag
git push -u origin HEAD $tag
if ($LASTEXITCODE -ne 0) { throw 'git push не прошёл' }
gh release create $tag "dist\MusicTransfer-Setup-$version.exe" --repo $repo --title "Версия $version" `
    --notes "Установщик: MusicTransfer-Setup-$version.exe. Установленная программа обновляется сама: кнопка «Проверить обновление»."
if ($LASTEXITCODE -ne 0) { throw 'Выпуск на GitHub не создан' }
Write-Host "Готово: https://github.com/$repo/releases/tag/$tag"
