---
name: music-transfer-dev
description: Test, run, live-check and build the music-transfer app (Spotify ↔ Yandex Music, PySide6) without touching the user's real accounts or tokens by accident — offline pytest with the network blocked, the GUI with a temp APPDATA, the rules for a live check on real accounts, and where the build plan is. Use for any change to music_transfer/ or tests/, and before running the app.
---

# music-transfer: develop and check

Project: `C:\Users\theme\.claude\workspace\music-transfer`; run everything from there. General test rules: the shared `testing` skill. Module map and service contract: `docs\development.md`.

## Tests

- `$env:HTTPS_PROXY='http://127.0.0.1:9'; .venv\Scripts\python.exe -m pytest -q` — the default run: any accidental HTTPS call fails fast. `tests\conftest.py` points `APPDATA` at a temp dir before imports.
- GUI tests run offscreen with fake services (`tests\test_gui.py`); a fake records which calls ran on the main thread, so a network call from the GUI thread is a test failure, not a hang.
- Screenshot of a window: the env vars at the top of `test_gui.py` plus `QApplication.setFont(QFont("Segoe UI", 9))` (shared `pyside6.md`).

## Running the app

- Without the real tokens:
  `$env:APPDATA = (New-Item -ItemType Directory -Force "$env:TEMP\mt-appdata").FullName; .venv\Scripts\python.exe main.py`
- Without a Spotify client ID in `config.json` the Spotify row asks for one; a successful login writes it to the real `config.json` next to the app — when trying the app by hand, expect that file to change.

## Live check (milestone 4)

- Only with the user's go, on their accounts, while they watch.
- The app only creates a new playlist and adds tracks; a test run uses a small source playlist. Never delete or edit an existing playlist, not even to clean up after a test; tell the user which playlist was created.
- Record what worked and the API behaviour seen in `docs\api-facts.md` / `docs\bugs.md`, with the date.

## Build (milestone 5)

- `powershell -ExecutionPolicy Bypass -File build.ps1` → `dist\MusicTransfer-Setup-<version>.exe`; details and what was checked in `docs\development.md` ("Build"). Needs Inno Setup 6 (per-user winget install). The version is `__version__` in `music_transfer\__init__.py`; never change `AppId` in `installer.iss`. Publishing is `release.ps1`, run by the user (it pushes); see `docs\development.md`, "Updates and releases".
- Test an installer without touching the user's install: `/VERYSILENT /SUPPRESSMSGBOXES /DIR=<temp> /NOICONS /TASKS=""`, start the installed exe with `QT_QPA_PLATFORM=offscreen` and a temp `APPDATA`, then `<temp>\unins000.exe /VERYSILENT`.
