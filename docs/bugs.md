# music-transfer: bugs and pitfalls

Entry format: Symptom → Cause → Fix → Verified (date, how).

## Offscreen Qt on Windows renders every glyph as a box

- Symptom: screenshots (`QWidget.grab()`) of the offscreen window show boxes instead of text; Qt warns `QFontDatabase: Cannot find font directory ...PySide6/lib/fonts`.
- Cause: the offscreen platform plugin has no bundled fonts and does not use the system ones.
- Fix: set `QT_QPA_FONTDIR=C:\Windows\Fonts` before Qt starts (`tests/test_gui.py` does it). Details in `docs\pyside6.md`.
- Verified 2026-10-27: probe script with a Cyrillic label, PNG readable, warning gone.

## Process dies with 0xC0000409 when exiting with a running QThread

- Symptom: the app (or a test) exits with code -1073740791 and no Python traceback.
- Cause: Qt aborts when a `QThread` is destroyed or the interpreter exits while the thread still runs.
- Fix: keep the only reference to the worker in the window, `wait()` for the previous worker before replacing it, and in `closeEvent` confirm and `os._exit(1)` when a worker is running (the core has no cancel). Details in `docs\pyside6.md`.
- Verified 2026-10-27: probe script exiting with a running QThread gave the exit code above.

## Spotify search with `market=from_token` → 403 "Insufficient client scope"

- Symptom: first live run (Yandex → Spotify, «Найти треки»): every search failed with 403 "Insufficient client scope"; login, `/me` and `/me/tracks` worked. The dialog also showed the whole request URL with the search text, and blamed User Management.
- Cause: `market=from_token` needs a scope the app does not ask for (granted scopes: the five in `SCOPES`, no `user-read-private`). Probably tied to the 2026 removal of `country` from `/me`; not confirmed in Spotify docs.
- Fix: search without `market`. With a user token Spotify applies the account's country anyway: `is_playable` still comes back and `isrc:` search works. The 401/403 message now keeps only the reason after spotipy's `<url>:\n` prefix.
- Verified 2026-10-27: read-only probe with the user's cached token: `market=from_token` → 403, no market → 1 item with `is_playable`; `isrc:<id>` found the same track. Tests `test_search_sends_no_market`, `test_forbidden_mentions_user_management_without_the_request_url`.

## A deadline check with `>` misses on Windows (`time.monotonic` ticks every 15.6 ms)

- Symptom: `test_login_stopped_expired_or_denied` failed now and then: the Yandex device-code loop polled again after `expires_in=0` instead of reporting the expired code.
- Cause: on Windows `time.monotonic()` is `GetTickCount64()` with a resolution of 0.015625 s, so after a 10 ms `Event.wait` it can still equal the deadline, and `monotonic() > deadline` is false.
- Fix: `>=` in `YandexService.login` (the library's own `device_auth` uses `>=` too).
- Verified 2026-10-27: `time.get_clock_info('monotonic')` shows the resolution; with `>=` the login tests passed 15 runs in a row, the full suite 5 runs.

## spotipy sleeps through a 429 silently, even for POST

- Symptom: after a 429 with `Retry-After: 3600` the worker would hang for hours with no progress, no `on_wait` call and no cancel; the "wait more than 5 min is an error" rule never fired.
- Cause: leaving 429 out of `status_forcelist` does not stop urllib3 from retrying it. `Retry.is_retry` retries any 429 that has a `Retry-After` header as long as `total` is non-zero (spotipy default `retries=3`), sleeps `Retry-After` (cap 6 h) and allows POST. 429 reaches our `call_with_retry` only after three silent sleeps. With `status_retries=0` the real 429 arrives without `Retry-After` ("Max Retries"), so that is not a fix.
- Fix: `spotipy.Spotify(..., retries=0, status_forcelist=(500, 502, 503, 504))`. The force list must stay non-empty: an empty one is replaced by a default that contains 429. Test `test_start_disables_urllib3_retries_so_429_reaches_our_layer` checks the adapter's `Retry`.
- Verified 2026-10-27: loopback server answering 429 with `Retry-After: 2`. Old config: 4 requests in 6.0 s. `retries=0`: 1 request, 429 with `Retry-After='2'`.

## spotipy turns an exhausted 5xx into a headerless 429

- Symptom: during a Spotify outage the user would see "rate limit exceeded", and a POST could be repeated (duplicate playlist or a doubled batch of up to 100 tracks).
- Cause: on `RetryError` spotipy raises `SpotifyException(429, ..., "<path>:\n Max Retries")` with no headers. A 500 on POST gave 4 POSTs from urllib3 plus up to 5 attempts of ours.
- Fix: `call_with_retry` recognizes this 429 (no headers, "Max Retries" in `msg`): writes (`write=True`) are never repeated, reads retry and then say "временно недоступен (ошибка сервера)" naming the host.
- Verified 2026-10-27: same loopback experiment (500 on POST: 4 requests with the old config, 1 with `retries=0`); the `Max Retries` cases are covered in `tests/test_common.py` and `tests/test_spotify.py`.

## Spotify playlists cannot be made private through the API

- Symptom: live 2026-10-28 (0.2.1, Yandex → Spotify, 6/6 tracks) the playlist was created correctly but shown as public.
- Cause: Spotify ignores `public: false` on create (a GET right after returned `public: true`) and on a follow-up `PUT /playlists/{id}`.
- Fix: none possible through the API. A «закрытые плейлисты» option (check box, then a switch) was tried and dropped at the user's choice; both services now create public playlists (Yandex ones used to be private), so the app behaves the same either way. A user who wants it private closes it in the Spotify app.
- Verified 2026-10-28: live, from sources with the private option on: the Spotify client showed the new playlist as public (the user's check).
