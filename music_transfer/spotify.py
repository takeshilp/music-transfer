import re, secrets, time, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import spotipy
from spotipy.cache_handler import CacheFileHandler
from spotipy.exceptions import SpotifyException, SpotifyOauthError
from spotipy.oauth2 import SpotifyPKCE

from .common import APP_DIR, LIKED, AppError, Playlist, Track, call_with_retry

API_HOST = "api.spotify.com"
AUTH_HOST = "accounts.spotify.com"
PORT = 8765
REDIRECT_URI = f"http://127.0.0.1:{PORT}/callback"
LOGIN_TIMEOUT = 180
CLIENT_ID = re.compile(r"[0-9a-fA-F]{32}")  # what the Dashboard shows as Client ID
SCOPES = ("playlist-read-private playlist-read-collaborative user-library-read playlist-modify-private "
          "playlist-modify-public user-library-modify")  # library-modify: following a playlist is PUT /me/library
DONE_PAGE = "<!doctype html><meta charset=utf-8><title>Spotify</title><p>Готово. Эту вкладку можно закрыть и вернуться в программу."


class _PKCE(SpotifyPKCE):
    def get_authorization_code(self, response=None):
        # spotipy would start its own blocking server / input(); login happens only in connect()
        raise SpotifyOauthError("login required", error="login_required")


class _Server(HTTPServer):
    allow_reuse_address = False  # on Windows SO_REUSEADDR lets a second process bind the same port


def _wait_for_code(url, state, open_url, timeout=LOGIN_TIMEOUT, stop=None):
    """Open the login page and wait for Spotify to redirect to the local port; returns the auth code, None if stopped."""
    result = {}

    class Handler(BaseHTTPRequestHandler):
        timeout = 5  # a browser preconnect that sends nothing must not block the single-threaded server

        def log_message(self, *args):
            pass

        def do_GET(self):
            u = urlparse(self.path)
            if u.path != "/callback":
                self.send_error(404)
                return
            result.update({k: v[0] for k, v in parse_qs(u.query).items()})
            body = DONE_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    try:
        server = _Server(("127.0.0.1", PORT), Handler)
    except OSError as e:
        raise AppError(f"Порт {PORT} занят — закройте другую копию программы") from e
    with server:
        server.timeout = 1
        open_url(url)
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            if stop and stop.is_set():  # checked every server.timeout
                return None
            server.handle_request()
    if not result:
        raise AppError(f"Вход в Spotify не завершён за 3 минуты. "
                       f"Проверьте Redirect URI приложения: http://127.0.0.1:{PORT}/callback")
    if "error" in result:
        raise AppError(f"Spotify отклонил вход: {result['error']}")
    if result.get("state") != state or "code" not in result:
        raise AppError("Ответ Spotify не совпал с запросом (state). Попробуйте войти ещё раз.")
    return result["code"]


def track_from_json(t):
    return Track(
        id=t.get("id"),
        title=t.get("name") or "",
        artists=[a["name"] for a in t.get("artists") or [] if a.get("name")],
        duration_ms=t.get("duration_ms") or 0,
        isrc=(t.get("external_ids") or {}).get("isrc"),
        available=t.get("is_playable") is not False,
        album=(t.get("album") or {}).get("name") or "")


def track_from_item(entry):
    t = entry.get("item") or entry.get("track")  # Feb 2026 rename `track` -> `item`, unverified live: read both
    if not t or t.get("type", "track") != "track":  # removed track or episode
        return None
    return track_from_json(t)


class SpotifyService:
    name = "Spotify"

    def __init__(self, client_id, slot=1):
        """slot 2 is a second account of the same user (moving from an old account): its own token file."""
        if not CLIENT_ID.fullmatch(client_id):
            raise AppError("Client ID Spotify — 32 символа из цифр и букв a–f со страницы приложения в Dashboard")
        self._cache = APP_DIR / ("spotify.json" if slot == 1 else f"spotify-{slot}.json")
        self._auth = _PKCE(client_id, REDIRECT_URI, scope=SCOPES, open_browser=False, requests_timeout=15,
                           cache_handler=CacheFileHandler(cache_path=str(self._cache)))
        self._sp = self._me = self.account = None
        self.on_wait = None  # optional on_wait(host, seconds): the GUI shows the wait (rate limit or a server-error retry)

    @property
    def connected(self):
        return self._sp is not None

    @property
    def account_id(self):
        return self._me

    @property
    def label(self):
        return f"{self.name} · {self.account}" if self.account else self.name

    def _start(self):
        # retries=0: urllib3 would otherwise sleep Retry-After silently (up to 6 h, even for POST) before 429 reaches
        # call_with_retry; a non-empty status_forcelist is needed, an empty one is replaced by a default that has 429
        sp = spotipy.Spotify(auth_manager=self._auth, retries=0, status_forcelist=(500, 502, 503, 504), requests_timeout=15)
        me = self._call(sp.me)
        self._me, self.account = me["id"], me.get("display_name") or me["id"]
        self._sp = sp

    def restore(self):
        """Log in from the cached token only, never opens a browser. A token from before a scope was added does not
        count: spotipy would reject it on the first call and that would read as an expired session."""
        token = self._auth.cache_handler.get_cached_token()
        if not token or not set(SCOPES.split()) <= set(token.get("scope", "").split()):
            return False
        self._start()
        return True

    def connect(self, open_url=webbrowser.open, stop=None):
        """Browser login; returns False if stop (threading.Event) was set."""
        APP_DIR.mkdir(parents=True, exist_ok=True)  # spotipy swallows a failed cache write
        state = secrets.token_urlsafe(16)
        self._auth.get_pkce_handshake_parameters()
        # show_dialog: Spotify shows whose account it is, with «Не вы?», instead of silently reusing the browser's login
        url = self._auth.get_authorize_url(state) + "&show_dialog=true"
        code = _wait_for_code(url, state, open_url, stop=stop)
        if code is None:
            return False
        try:
            call_with_retry(lambda: self._auth.get_access_token(code, check_cache=False), AUTH_HOST, on_wait=self.on_wait)
        except SpotifyOauthError as e:
            raise AppError(f"Spotify не выдал токен: {e.error_description or e.error}") from e
        self._start()
        return True

    def disconnect(self):
        self._sp = self._me = self.account = None
        self._cache.unlink(missing_ok=True)

    def _call(self, fn, *a, write=False, **kw):
        try:
            return call_with_retry(lambda: fn(*a, **kw), API_HOST, on_wait=self.on_wait, write=write)
        except SpotifyOauthError as e:
            if e.error in ("invalid_grant", "login_required"):
                self.disconnect()
                raise AppError("Сессия Spotify истекла (вход действует 6 месяцев) — нажмите «Войти»") from e
            raise AppError(f"Ошибка входа Spotify: {e.error_description or e.error or e}") from e
        except SpotifyException as e:
            reason = str(e.msg).rsplit(":\n", 1)[-1].strip()  # spotipy puts the request URL (the user's search text) first
            if e.http_status in (401, 403):
                raise AppError(f"Spotify отказал в доступе ({e.http_status}): {reason}. Если это не аккаунт владельца "
                               "приложения, владелец должен добавить его в User Management.") from e
            raise AppError(f"Ошибка Spotify ({e.http_status}): {reason}") from e

    def _pages(self, fn, *a, **kw):
        page = self._call(fn, *a, **kw)
        while True:
            yield from page["items"]
            if not page["next"]:
                return
            page = self._call(self._sp.next, page)

    def playlists(self):
        liked = self._call(self._sp.current_user_saved_tracks, limit=1)["total"]
        out = [Playlist(LIKED, "Любимые треки", liked)]
        for p in self._pages(self._sp.current_user_playlists, limit=50):
            if p:
                count = (p.get("items") or p.get("tracks") or {}).get("total", 0)
                # Dev Mode returns no items for playlists the user neither owns nor collaborates on: those can only
                # be followed from another account
                followed = p["owner"]["id"] != self._me and not p.get("collaborative")
                out.append(Playlist(p["id"], p["name"], count, followed))
        return out

    def follow(self, playlist):
        self._call(self._sp.current_user_follow_playlist, playlist.id, write=True)

    def tracks(self, playlist):
        if playlist.id == LIKED:
            entries = self._pages(self._sp.current_user_saved_tracks, limit=50)
        else:
            entries = self._pages(self._sp.playlist_items, playlist.id, limit=50, additional_types=("track",))
        return [t for t in map(track_from_item, entries) if t]

    def _search(self, q):
        # no market=from_token: with our scopes it answers 403 "Insufficient client scope"; the user token's country
        # applies anyway, is_playable still comes back (both checked live 2026-10-27)
        r = self._call(self._sp.search, q=q, type="track", limit=10)  # 10 is the API max now
        return [track_from_json(t) for t in r["tracks"]["items"] if t]

    def search(self, artist, title):
        return self._search(f"{artist} {title}")

    def search_isrc(self, isrc):
        return self._search(f"isrc:{isrc}")

    def create_playlist(self, name, tracks):
        """Creates a new private playlist; never writes to any id it did not just create."""
        pid = self._call(self._sp.current_user_playlist_create, name, public=False, write=True)["id"]
        ids = [t.id for t in tracks]
        for i in range(0, len(ids), 100):  # API max per request
            self._call(self._sp.playlist_add_items, pid, ids[i:i + 100], write=True)
        return pid
