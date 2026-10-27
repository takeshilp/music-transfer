# music-transfer

Windows desktop app (Python + PySide6) that copies playlists and liked tracks between Spotify and Yandex Music, both directions. SoundCloud was dropped: its API needs an Artist Pro subscription. Original spec: `build-prompt.md` (kept as written, with its old paths; local only: git-ignored because the repository is public).

Status: milestone 3 (GUI) is done and tested offline (core with fakes, window offscreen), including login from the window: Yandex by OAuth device code, Spotify Client ID typed in and saved to `config.json` after the first login; also moving to a second account of the same service (exact copy, liked tracks into a named playlist, subscriptions followed on request). The live check on real accounts is milestone 4: login and Yandex → Spotify search (2026-10-27) and a Yandex → Spotify transfer from the installed 0.2.1 (2026-10-28) work; writes to Yandex, following and the private switch are not yet tried live.

Paths below are relative to this folder.

## Commands

Run from this folder:

- Tests: `.venv\Scripts\python.exe -m pytest -q`
- Tests with the network blocked: `$env:HTTPS_PROXY='http://127.0.0.1:9'; .venv\Scripts\python.exe -m pytest -q`
- App: `.venv\Scripts\python.exe main.py` (use a temp `APPDATA` unless you mean to touch the real tokens)
- `run.bat` (double-click): runs the offline tests, then the app in a console so a crash shows its traceback.
- Installer: `powershell -ExecutionPolicy Bypass -File build.ps1` → `dist\MusicTransfer-Setup-<version>.exe` (tests, PyInstaller, Inno Setup; details in `docs\development.md`, "Build").
- Release: `powershell -ExecutionPolicy Bypass -File release.ps1` — the user runs it (it pushes to the public GitHub repo and publishes the installer); Claude never pushes. Version: `__version__` in `music_transfer\__init__.py`. It uses the real `%APPDATA%` — the user's own check.

## Rules

- Never modify or delete existing playlists: the only writes are creating a new playlist and adding tracks to it, marking that new playlist private when «Создавать закрытые плейлисты» is ticked, and following (subscribing to) someone else's playlist the user ticked when moving to a second account.
- Tokens live only in `%APPDATA%\music-transfer\`. `config.json` (Spotify client ID) sits next to the app, written by the app after a successful Spotify login (other keys kept); no hardcoded client ID. Tests never write it (`tests\test_gui.py` stubs `save_config`).
- No proxy code; requests uses `HTTPS_PROXY` or the Windows proxy by itself.
- No new dependencies without asking (`requirements.txt` is pinned).
- No writes to real accounts without the user's go. Tests are offline and redirect `APPDATA` (`tests\conftest.py`).
- UI and error strings in Russian, code comments in English. No log file.

## Skill and docs

- `.claude\skills\music-transfer-dev\` — test, run, live-check and build the app safely.
- Docs index: `docs\INDEX.md`. Read it before changing the code, and the `bugs.md` entries for the area you touch. When you create a significant doc, add it to `docs\INDEX.md` in the same task.
