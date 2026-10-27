# Music Transfer

## What it is

Music Transfer is a Windows desktop app (Python 3.12, PySide6, Russian UI) that copies playlists and liked tracks between Spotify and Yandex Music in either direction, or from an old account to a new one on the same service, for the user and a few friends on their own PCs. It only ever creates new playlists (and, when moving accounts, follows the playlists you tick); existing ones are never changed. Status: works on real accounts (login, search); installer and self-update published as [GitHub releases](https://github.com/takeshilp/music-transfer/releases). Writes to real accounts are still being checked.

## Quick start

```powershell
cd $env:USERPROFILE\.claude\workspace\music-transfer
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe main.py   # «Войти» for each service; Spotify asks for its Client ID once
```

New venv: `python -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt`.

## Structure

```
music-transfer\
├── README.md, CLAUDE.md
├── main.py               entry point, calls music_transfer.gui.run()
├── music_transfer\       common, matching, transfer, spotify, yandex, gui, theme (+ assets\ icons)
├── tests\                pytest, offline, fakes for both services
├── requirements.txt      pinned
├── config.example.json   shape of config.json (Spotify client ID); the app writes config.json itself
├── build.ps1, installer.iss   the installer build (PyInstaller + Inno Setup) → dist\
├── release.ps1           publish a version to the public GitHub repo (run by the owner)
├── build-prompt.md       original spec (local only, git-ignored: personal context)
├── .venv\
├── docs\                 INDEX.md, development.md, bugs.md, api-facts.md
└── .claude\skills\       music-transfer-dev
```

## Docs

[docs/INDEX.md](docs/INDEX.md)

## Common tasks

- Run the tests offline: `$env:HTTPS_PROXY='http://127.0.0.1:9'; .venv\Scripts\python.exe -m pytest -q`.
- Try the app without touching the real tokens: start it with `APPDATA` pointed at a temp folder (the `music-transfer-dev` skill has the command).
- Look up an API fact or limit: [docs/api-facts.md](docs/api-facts.md).
- Build the installer for friends: `powershell -ExecutionPolicy Bypass -File build.ps1` → `dist\MusicTransfer-Setup-<version>.exe`.
- Publish a new version (installed copies update themselves via «Проверить обновление»): raise `__version__` in `music_transfer\__init__.py`, note it in `docs\changelog.md`, commit, then `powershell -ExecutionPolicy Bypass -File release.ps1` (once before: `gh auth login`).

## Owner

The repository owner on GitHub (see `REPO` in `music_transfer/update.py`).
