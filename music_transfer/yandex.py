import json, re, time, webbrowser

from yandex_music import Client
from yandex_music.exceptions import DeviceAuthError, UnauthorizedError, YandexMusicError
from yandex_music.utils.difference import Difference

from .common import APP_DIR, LIKED, AppError, Playlist, Track, call_with_retry

API_HOST = "api.music.yandex.net"
OAUTH_HOST = "oauth.yandex.ru"
TOKEN_URL = "https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d"  # GUI hint
# shortcut: no documented insert limit (the library inserts 1, the server has a 413 path); lower if 413 shows in the live check
ADD_CHUNK = 100
FETCH_CHUNK = 500  # tracks() sends all ids in one POST; chunking keeps a 5000-track "Мне нравится" under the timeout


def parse_token(text):
    """Accepts a bare token or the whole redirect URL with #access_token=..."""
    m = re.search(r"access_token=([^&\s]+)", text)
    return (m.group(1) if m else text).strip()


def track_from_model(t):
    album = t.albums[0] if t.albums else None
    album_id = str(album.id) if album and album.id is not None else None
    return Track(
        id=str(t.id),
        title=f"{t.title} ({t.version})" if t.version else t.title or "",
        artists=[a.name for a in t.artists or [] if a.name] or ([t.ugc_artist_name] if t.ugc_artist_name else []),
        duration_ms=t.duration_ms or 0,
        isrc=t.isrc,
        available=bool(t.available) and album_id is not None,  # a track cannot be inserted without an album id
        album=(album.title or "") if album else "",
        album_id=album_id)


class YandexService:
    name = "Яндекс Музыка"

    def __init__(self, slot=1):
        """slot 2 is a second account of the same user (moving from an old account): its own token file."""
        self._client = self.account = None
        self._token_file = APP_DIR / ("yandex.json" if slot == 1 else f"yandex-{slot}.json")
        self.on_wait = None  # optional on_wait(host, seconds): the GUI shows the wait (rate limit or a server-error retry)

    @property
    def connected(self):
        return self._client is not None

    @property
    def account_id(self):
        return self._client.account_uid if self._client else None

    @property
    def label(self):
        return f"{self.name} · {self.account}" if self.account else self.name

    def _start(self, token):
        c = Client(token)
        c.request.set_timeout(15)
        self._call(c.init)
        if c.account_uid is None:
            raise AppError("Яндекс Музыка не приняла токен")
        acc = c.me.account if c.me else None
        self._client, self.account = c, (acc.display_name or acc.login) if acc else None

    def restore(self):
        try:
            token = json.loads(self._token_file.read_text(encoding="utf-8"))["token"]
        except (OSError, ValueError, KeyError):
            return False
        self._start(token)
        return True

    def connect(self, token_text):
        token = parse_token(token_text)
        if not token:
            raise AppError("Вставьте токен Яндекс Музыки")
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", token):  # HTTP headers are latin-1: Cyrillic would crash with UnicodeEncodeError
            raise AppError("Это не похоже на токен Яндекс Музыки: вставьте access_token или всю ссылку из адресной строки")
        self._start(token)  # saved only after a successful start
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self._token_file.write_text(json.dumps({"token": token}), encoding="utf-8")

    def login(self, on_code, stop, open_url=webbrowser.open):
        """OAuth device flow: on_code(user_code, url), open the confirmation page, poll until the user confirms.

        Returns False if stop (threading.Event) was set."""
        c = Client()
        c.request.set_timeout(15)
        code = self._call(c.request_device_code, host=OAUTH_HOST)
        on_code(code.user_code, code.verification_url)
        open_url(code.verification_url)
        deadline = time.monotonic() + code.expires_in
        while not stop.wait(code.interval or 5):
            token = self._call(c.poll_device_token, code.device_code, host=OAUTH_HOST)  # None while pending
            if token:
                self.connect(token.access_token)
                return True
            if time.monotonic() >= deadline:
                raise AppError("Код входа Яндекса истёк — нажмите «Войти» ещё раз")
        return False

    def disconnect(self):
        self._client = self.account = None
        self._token_file.unlink(missing_ok=True)

    def _call(self, fn, *a, host=API_HOST, **kw):
        try:
            return call_with_retry(lambda: fn(*a, **kw), host, on_wait=self.on_wait)
        except DeviceAuthError as e:  # expired_token, access_denied, ...
            raise AppError(f"Яндекс не подтвердил вход ({e}). Нажмите «Войти» ещё раз.") from e
        except UnauthorizedError as e:
            # a 403 can come from a foreign proxy exit, so the saved token is kept
            self._client = None
            raise AppError("Яндекс Музыка отклонила токен (401/403). Если токен свежий — проверьте, "
                           "что Яндекс идёт без прокси; иначе получите новый токен.") from e
        except YandexMusicError as e:
            # the library appends the raw response body (bytes repr, a whole HTML page on a 503): keep the text up to the status
            text = re.sub(r": b['\"].*", "", str(e), flags=re.S)
            raise AppError(f"Ошибка Яндекс Музыки ({host}): {text}") from e

    def playlists(self):
        liked = self._call(self._client.users_likes_tracks)
        out = [Playlist(LIKED, "Мне нравится", len(liked or []))]
        for p in self._call(self._client.users_playlists_list):
            out.append(Playlist(str(p.kind), p.title or "", p.track_count or 0))
        for like in self._call(self._client.users_likes_playlists) or []:  # someone else's playlists, "owner:kind"
            if p := like.playlist:
                out.append(Playlist(p.playlist_id, p.title or "", p.track_count or 0, followed=True))
        return out

    def follow(self, playlist):
        self._call(self._client.users_likes_playlists_add, playlist.id)

    def tracks(self, playlist):
        if playlist.id == LIKED:
            shorts = list(self._call(self._client.users_likes_tracks) or [])
        else:
            pl = self._call(self._client.users_playlists, int(playlist.id))
            shorts = list(pl.tracks or [])
        need = [s.track_id for s in shorts if s.track is None]
        full = {}
        for i in range(0, len(need), FETCH_CHUNK):
            for t in self._call(self._client.tracks, need[i:i + FETCH_CHUNK]):
                full[str(t.id)] = t
        models = (s.track or full.get(str(s.id)) for s in shorts)
        return [track_from_model(m) for m in models if m]

    def search(self, artist, title):
        r = self._call(self._client.search, f"{artist} {title}", type_="track")
        return [track_from_model(t) for t in r.tracks.results] if r and r.tracks else []

    def search_isrc(self, isrc):
        return []  # Yandex has no ISRC search; ISRC is compared on the text-search results

    def create_playlist(self, name, tracks):
        """Creates a new private playlist; every write goes to the kind it just created."""
        pl = self._call(self._client.users_playlists_create, name, visibility="private")
        if pl is None:
            raise AppError("Яндекс Музыка не создала плейлист")
        kind, rev, at = pl.kind, pl.revision, 0
        for i in range(0, len(tracks), ADD_CHUNK):
            chunk = tracks[i:i + ADD_CHUNK]
            diff = Difference().add_insert(at, [{"id": t.id, "album_id": t.album_id} for t in chunk]).to_json()
            pl = self._call(self._client.users_playlists_change, kind, diff, rev)
            rev, at = pl.revision, at + len(chunk)
        return str(kind)
