import http.client
import json
import socket
import threading

import pytest
import spotipy
from spotipy.exceptions import SpotifyException, SpotifyOauthError

from music_transfer import spotify
from music_transfer.common import APP_DIR, LIKED, AppError, Playlist, Track
from music_transfer.spotify import SpotifyService, _wait_for_code, track_from_item

CID = "0123456789abcdef0123456789ABCDEF"


def raw(**kw):
    return {"type": "track", "id": "t1", "name": "Song", "artists": [{"name": "A"}, {"name": "B"}],
            "duration_ms": 1234, "external_ids": {"isrc": "US1"}, "album": {"name": "Alb"}, **kw}


def test_track_from_item_both_keys():
    for key in ("item", "track"):
        t = track_from_item({key: raw()})
        assert (t.id, t.title, t.artists, t.duration_ms, t.isrc, t.album) == ("t1", "Song", ["A", "B"], 1234, "US1", "Alb")


def test_track_from_item_skips_episodes_and_removed():
    assert track_from_item({"track": raw(type="episode")}) is None
    assert track_from_item({"track": None}) is None


def test_local_file_has_no_id_and_unplayable_is_unavailable():
    assert track_from_item({"track": raw(id=None)}).id is None
    assert track_from_item({"track": raw(is_playable=False)}).available is False


@pytest.mark.parametrize("cid", ["", "cid", CID + "0", CID[:-1] + "g"])
def test_client_id_must_be_32_hex(cid):
    with pytest.raises(AppError, match="32 символа"):
        SpotifyService(cid)


class FakeSp:
    def __init__(self):
        self.calls = []

    def current_user_playlist_create(self, name, public=True):
        self.calls.append(("create", name, public))
        return {"id": "NEW"}

    def playlist_add_items(self, pid, ids):
        self.calls.append(("add", pid, len(ids)))


def test_create_playlist_chunks_to_the_new_playlist_only():
    svc = SpotifyService(CID)
    svc._sp = FakeSp()
    pid = svc.create_playlist("N", [Track(f"i{i}", "s", ["a"]) for i in range(250)])
    assert pid == "NEW"
    assert svc._sp.calls == [("create", "N", False), ("add", "NEW", 100), ("add", "NEW", 100), ("add", "NEW", 50)]


def test_create_playlist_does_not_repeat_write_after_server_error():
    class Failing(FakeSp):
        def playlist_add_items(self, pid, ids):
            self.calls.append(("add", pid, len(ids)))
            raise SpotifyException(429, -1, "/v1/playlists/NEW/items:\n Max Retries")
    svc = SpotifyService(CID)
    svc._sp = Failing()
    with pytest.raises(AppError, match="временно недоступен"):
        svc.create_playlist("N", [Track("i", "s", ["a"])])
    assert svc._sp.calls == [("create", "N", False), ("add", "NEW", 1)]


def test_start_disables_urllib3_retries_so_429_reaches_our_layer(monkeypatch):
    monkeypatch.setattr(spotipy.Spotify, "me", lambda self: {"id": "me"})
    svc = SpotifyService(CID)
    svc._start()
    retry = svc._sp._session.get_adapter("https://api.spotify.com").max_retries
    assert retry.is_retry("GET", 429, True) is False  # urllib3 would sleep Retry-After silently
    assert retry.is_retry("GET", 503, False) is True  # 5xx stays in the force list


def test_invalid_grant_drops_cache_and_session():
    svc = SpotifyService(CID)
    svc._sp = object()
    APP_DIR.mkdir(parents=True, exist_ok=True)
    svc._cache.write_text("{}")

    def dead():
        raise SpotifyOauthError("x", error="invalid_grant")
    with pytest.raises(AppError, match="Сессия Spotify истекла"):
        svc._call(dead)
    assert not svc._cache.exists() and not svc.connected


def test_forbidden_mentions_user_management_without_the_request_url():
    svc = SpotifyService(CID)

    def denied():  # spotipy puts the whole URL, with the user's search text, before the reason
        raise SpotifyException(403, -1, "https://api.spotify.com/v1/search?q=LIL+%D1%8F:\n Insufficient client scope")
    with pytest.raises(AppError, match="User Management") as ei:
        svc._call(denied)
    assert "Insufficient client scope" in str(ei.value) and "https://" not in str(ei.value)


def test_search_sends_no_market():
    """market=from_token answers 403 "Insufficient client scope" to our scopes (live, 2026-10-27)."""
    class Sp:
        def search(self, **kw):
            self.kw = kw
            return {"tracks": {"items": [raw()]}}
    svc = SpotifyService(CID)
    svc._sp = Sp()
    assert [t.id for t in svc.search("A", "Song")] == ["t1"] and "market" not in svc._sp.kw


def test_service_passes_on_wait_to_retry():
    svc, waits, n = SpotifyService(CID), [], []
    svc.on_wait = lambda h, s: waits.append((h, s))

    def limited():
        if not n:
            n.append(1)
            raise SpotifyException(429, -1, "slow", headers={"Retry-After": "0"})
        return "ok"
    assert svc._call(limited) == "ok" and waits == [("api.spotify.com", 0)]


class PagedSp:
    def __init__(self):
        self.pages = [
            {"items": [{"id": "own", "name": "Mine", "owner": {"id": "me"}, "items": {"total": 3}},
                       {"id": "foreign", "name": "Other", "owner": {"id": "x"}, "tracks": {"total": 9}}], "next": "p2"},
            {"items": [{"id": "collab", "name": "Shared", "owner": {"id": "x"}, "collaborative": True,
                        "tracks": {"total": 5}}], "next": None}]

    def current_user_saved_tracks(self, limit):
        return {"total": 42}

    def current_user_playlists(self, limit):
        return self.pages[0]

    def next(self, page):
        return self.pages[1]


def test_playlists_marks_foreign_ones_as_followed_and_follows_pages():
    svc = SpotifyService(CID)
    svc._sp, svc._me = PagedSp(), "me"
    assert svc.playlists() == [Playlist(LIKED, "Любимые треки", 42), Playlist("own", "Mine", 3),
                               Playlist("foreign", "Other", 9, followed=True), Playlist("collab", "Shared", 5)]


def test_follow_and_account_label(monkeypatch):
    monkeypatch.setattr(spotipy.Spotify, "me", lambda self: {"id": "u1", "display_name": "Taki"})
    monkeypatch.setattr(spotipy.Spotify, "current_user_follow_playlist", lambda self, pid: calls.append(pid))
    calls, svc = [], SpotifyService(CID)
    assert svc.label == "Spotify"
    svc._start()
    svc.follow(Playlist("f1", "Other", 9, followed=True))
    assert (svc.label, svc.account_id, calls) == ("Spotify · Taki", "u1", ["f1"])


def test_second_slot_has_its_own_token_and_old_scopes_need_a_new_login(monkeypatch):
    svc, started = SpotifyService(CID, 2), []
    assert svc._cache.name == "spotify-2.json"
    monkeypatch.setattr(svc, "_start", lambda: started.append(1))
    APP_DIR.mkdir(parents=True, exist_ok=True)
    old = "playlist-read-private playlist-read-collaborative user-library-read playlist-modify-private playlist-modify-public"
    svc._cache.write_text(json.dumps({"access_token": "a", "refresh_token": "r", "expires_at": 9e9, "scope": old}))
    assert svc.restore() is False and started == []  # a token from before user-library-modify
    svc._cache.write_text(json.dumps({"access_token": "a", "refresh_token": "r", "expires_at": 9e9, "scope": spotify.SCOPES}))
    assert svc.restore() is True and started == [1]
    svc._cache.unlink()


def test_login_page_always_asks_which_account(monkeypatch):
    urls = []
    monkeypatch.setattr(spotify, "_wait_for_code", lambda url, *a, **k: urls.append(url))  # None: as if cancelled
    assert SpotifyService(CID).connect(open_url=None) is False
    assert urls[0].endswith("&show_dialog=true") and "client_id=" + CID in urls[0]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def browser(port, *paths):
    def open_url(url):
        def go():
            for p in paths:
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                c.request("GET", p)
                c.getresponse().read()
                c.close()
        threading.Thread(target=go).start()
    return open_url


def test_wait_for_code_ignores_favicon_and_returns_code(monkeypatch):
    port = free_port()
    monkeypatch.setattr(spotify, "PORT", port)
    assert _wait_for_code("u", "S1", browser(port, "/favicon.ico", "/callback?code=c1&state=S1"), timeout=10) == "c1"


def test_wait_for_code_wrong_state(monkeypatch):
    port = free_port()
    monkeypatch.setattr(spotify, "PORT", port)
    with pytest.raises(AppError, match="state"):
        _wait_for_code("u", "S1", browser(port, "/callback?code=c1&state=bad"), timeout=10)


def test_wait_for_code_denied(monkeypatch):
    port = free_port()
    monkeypatch.setattr(spotify, "PORT", port)
    with pytest.raises(AppError, match="access_denied"):
        _wait_for_code("u", "S1", browser(port, "/callback?error=access_denied&state=S1"), timeout=10)


def test_wait_for_code_timeout(monkeypatch):
    monkeypatch.setattr(spotify, "PORT", free_port())
    with pytest.raises(AppError, match="не завершён"):
        _wait_for_code("u", "S1", lambda url: None, timeout=1)


def test_wait_for_code_returns_none_when_stopped(monkeypatch):
    monkeypatch.setattr(spotify, "PORT", free_port())
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    assert _wait_for_code("u", "S1", lambda url: None, timeout=10, stop=stop) is None


def test_wait_for_code_busy_port(monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        monkeypatch.setattr(spotify, "PORT", s.getsockname()[1])
        with pytest.raises(AppError, match="занят"):
            _wait_for_code("u", "S1", lambda url: None, timeout=1)
