# Changelog

## 0.2.2 — 2026-10-28

- The app is called Music Transfer: window title, Start-menu and desktop shortcuts, the entry in Windows «Приложения». The update removes the old «Перенос плейлистов» shortcuts.
- The «Откуда» / «Куда» lists open below the box, rounded and dark like the rest of the window, without the bright green highlight.
- «Создавать закрытые плейлисты» in «Режим». New playlists are public by default on both services (Yandex ones used to be private); tick it to make them private. In Spotify the app marks the playlist private right after creating it, because Spotify ignores that on creation.
- Installers left in `%TEMP%` by past updates are removed at start.

## 0.2.1 — 2026-10-27

- «Откуда» and «Куда» each take a full row, so account names like «Spotify · ник» are no longer cut; the results table got wider too.
- The first release delivered through «Проверить обновление».

## 0.2.0 — 2026-10-27

- «Проверить обновление»: downloads the latest GitHub release, checks it and installs it silently, then the app starts again.
- Moving to a second account of the same service: exact copy without search, liked tracks into a playlist you name, subscriptions followed when ticked.
- Login from the window: Yandex by a device code, the Spotify client ID typed in (with a guide and clipboard pick-up), «Отмена» for login waits.
- Dark theme in Spotify colours.
- Fix: Spotify search no longer sends `market=from_token` (403 "Insufficient client scope").
- Installer: PyInstaller + Inno Setup, per-user, no admin.

## 0.1.0 — 2026-10-27

- First installer build, local only (not published).
