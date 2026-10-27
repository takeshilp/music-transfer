import json, threading
from types import SimpleNamespace as NS

import pytest
from yandex_music.exceptions import DeviceAuthError, NetworkError, UnauthorizedError

from music_transfer import yandex
from music_transfer.common import APP_DIR, LIKED, AppError, Playlist, Track
from music_transfer.yandex import YandexService, parse_token, track_from_model


def model(id=1, title="Song", version=None, artists=("A",), albums=(NS(id=7, title="Alb"),), **kw):
    return NS(id=id, title=title, version=version, artists=[NS(name=a) for a in artists], ugc_artist_name=None,
              albums=list(albums), duration_ms=1000, isrc="US1", available=True, **kw)


def test_track_from_model():
    t = track_from_model(model(version="Live"))
    assert (t.id, t.title, t.artists, t.album, t.album_id, t.isrc, t.available) == \
        ("1", "Song (Live)", ["A"], "Alb", "7", "US1", True)


def test_no_album_means_unavailable():
    t = track_from_model(model(albums=()))
    assert t.album_id is None and t.available is False


def test_ugc_artist_fallback():
    m = model(artists=())
    m.ugc_artist_name = "Uploader"
    assert track_from_model(m).artists == ["Uploader"]


def test_parse_token():
    assert parse_token("  abc123  ") == "abc123"
    assert parse_token("https://music.yandex.ru/#access_token=tok-1&token_type=bearer&expires_in=1") == "tok-1"


class FakeClient:
    def __init__(self):
        self.calls, self.rev = [], 1

    def users_playlists_create(self, name, visibility):
        self.calls.append(("create", name, visibility))
        return NS(kind=55, revision=self.rev)

    def users_playlists_change(self, kind, diff, rev):
        self.calls.append(("change", kind, json.loads(diff), rev))
        self.rev += 1
        return NS(kind=kind, revision=self.rev)


def test_create_playlist_chains_revision_and_position():
    svc, c = YandexService(), FakeClient()
    svc._client = c
    tracks = [Track(str(i), "s", ["a"], album_id=str(i + 1000)) for i in range(150)]
    assert svc.create_playlist("N", tracks) == "55"
    assert c.calls[0] == ("create", "N", "private")
    (_, k1, d1, r1), (_, k2, d2, r2) = c.calls[1:]
    assert (k1, k2, r1, r2) == (55, 55, 1, 2)
    assert (d1[0]["at"], len(d1[0]["tracks"])) == (0, 100) and (d2[0]["at"], len(d2[0]["tracks"])) == (100, 50)
    assert d1[0]["tracks"][0] == {"id": "0", "albumId": "1000"}


def test_tracks_fetches_missing_models_keeps_order_skips_removed():
    fetched = []

    class C:
        def users_playlists(self, kind):
            assert kind == 3
            return NS(tracks=[NS(id="1", track=model(1), track_id="1:7"), NS(id="2", track=None, track_id="2:7"),
                              NS(id="3", track=None, track_id="3:7")])

        def tracks(self, ids):
            fetched.append(list(ids))
            return [model(2)]  # id 3 was removed and is not returned
    svc = YandexService()
    svc._client = C()
    assert [t.id for t in svc.tracks(Playlist("3", "P", 3))] == ["1", "2"]
    assert fetched == [["2:7", "3:7"]]


def test_playlists_lists_liked_first_and_subscriptions_last():
    followed = []

    class C:
        def users_likes_tracks(self):
            return [1, 2]

        def users_playlists_list(self):
            return [NS(kind=9, title="P", track_count=4)]

        def users_likes_playlists(self):
            return [NS(playlist=NS(playlist_id="77:3", title="Чужой", track_count=8)), NS(playlist=None)]

        def users_likes_playlists_add(self, pid):
            followed.append(pid)
    svc = YandexService()
    svc._client = C()
    assert svc.playlists() == [Playlist(LIKED, "Мне нравится", 2), Playlist("9", "P", 4),
                               Playlist("77:3", "Чужой", 8, followed=True)]
    svc.follow(Playlist("77:3", "Чужой", 8, followed=True))
    assert followed == ["77:3"]


def test_second_slot_has_its_own_token_file():
    assert YandexService(2)._token_file.name == "yandex-2.json" and YandexService()._token_file.name == "yandex.json"


def test_unauthorized_keeps_token_file():
    svc = YandexService()
    svc._client = object()
    APP_DIR.mkdir(parents=True, exist_ok=True)
    svc._token_file.write_text('{"token": "t"}')

    def denied():
        raise UnauthorizedError("403")
    with pytest.raises(AppError, match="отклонила токен"):
        svc._call(denied)
    assert svc._token_file.exists() and not svc.connected
    svc.disconnect()
    assert not svc._token_file.exists()


def test_server_error_text_is_trimmed_and_names_host():
    svc = YandexService()

    def broken():
        raise NetworkError(f"Unknown HTTPError (503): {b'<html>' + b'x' * 5000 + b'</html>'}")
    with pytest.raises(AppError) as ei:
        svc._call(broken)
    assert str(ei.value) == "Ошибка Яндекс Музыки (api.music.yandex.net): Unknown HTTPError (503)"


def test_connect_rejects_empty_token_and_restore_without_file():
    svc = YandexService()
    svc.disconnect()
    assert svc.restore() is False
    with pytest.raises(AppError, match="токен"):
        svc.connect("   ")
    with pytest.raises(AppError, match="не похоже"):
        svc.connect("вставьте сюда токен")


class FakeOAuth:
    """Stands for yandex_music.Client in the device flow; polls: what each poll returns or raises."""
    def __init__(self, polls, expires_in=60):
        self.polls, self.expires_in, self.request = list(polls), expires_in, NS(set_timeout=lambda t: None)

    def request_device_code(self):
        return NS(device_code="dc", user_code="UC", verification_url="https://ya.ru/device",
                  expires_in=self.expires_in, interval=0.01)

    def poll_device_token(self, device_code):
        assert device_code == "dc"
        p = self.polls.pop(0)
        if isinstance(p, Exception):
            raise p
        return p


def login(monkeypatch, client, stop=None):
    monkeypatch.setattr(yandex, "Client", lambda: client)
    svc, seen = YandexService(), []
    monkeypatch.setattr(svc, "connect", lambda token: seen.append(("connect", token)))
    ok = svc.login(lambda code, url: seen.append((code, url)), stop or threading.Event(), lambda url: seen.append(url))
    return ok, seen


def test_login_polls_until_confirmed_then_connects(monkeypatch):
    c = FakeOAuth([None, None, NS(access_token="tok")])
    assert login(monkeypatch, c) == (True, [("UC", "https://ya.ru/device"), "https://ya.ru/device", ("connect", "tok")])
    assert c.polls == []


def test_login_stopped_expired_or_denied(monkeypatch):
    stop = threading.Event()
    stop.set()
    assert login(monkeypatch, FakeOAuth([]), stop)[0] is False
    with pytest.raises(AppError, match="истёк"):
        login(monkeypatch, FakeOAuth([None], expires_in=0))
    with pytest.raises(AppError, match="не подтвердил вход"):
        login(monkeypatch, FakeOAuth([DeviceAuthError("access_denied")]))
