# Changelog

## 0.2.2 — 2026-10-28

- The app is called Music Transfer: window title, Start-menu and desktop shortcuts, the entry in Windows «Приложения». The update removes the old «Перенос плейлистов» shortcuts.
- The «Откуда» / «Куда» lists open below the box, rounded and dark like the rest of the window, without the bright green highlight.
- New playlists are public on both services; Yandex ones used to be private. Spotify does not let apps make private playlists, so both now behave the same; close one by hand in the service's app if needed.
- Installers left in `%TEMP%` by past updates are removed at start.
- «Отмена» for «Найти треки» and «Перенести». A search stops right away, rate-limit waits included, and drops its results. A transfer finishes the playlist being written (the status says so at once), shows which playlists were created, and «Перенести» continues with the rest; with a single playlist there is nothing to stop, so no «Отмена».
- A track the search missed (or matched wrong) can be fixed by hand before «Перенести»: double-click its row and choose from the target service's search results (when artist and title find nothing, it also searches the title alone, since the target may credit another artist; edit the artist or title and «Искать» again if needed), or «Не переносить». Picked rows say «вручную», get the same pick in every playlist, and are left out of the not-found CSV; region-blocked tracks are listed but cannot be chosen.

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
