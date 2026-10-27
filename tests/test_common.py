import pytest
import requests
from spotipy.exceptions import SpotifyException
from yandex_music.exceptions import NetworkError, TimedOutError

from music_transfer.common import AppError, call_with_retry, load_config, save_config


def flaky(*errors, result="ok"):
    errs = list(errors)

    def fn():
        if errs:
            raise errs.pop(0)
        return result
    return fn


def r429(retry_after=None):
    return SpotifyException(429, -1, "limit", headers={"Retry-After": retry_after} if retry_after else {})


def test_spotify_429_waits_retry_after():
    slept = []
    assert call_with_retry(flaky(r429("7")), "h", sleep=slept.append) == "ok"
    assert slept == [7]


def test_429_without_header_uses_default():
    slept = []
    call_with_retry(flaky(r429()), "h", sleep=slept.append)
    assert slept == [5]


def test_yandex_429_waits_default():
    slept = []
    call_with_retry(flaky(NetworkError("Bad response (429): b''")), "h", sleep=slept.append)
    assert slept == [5]


def test_on_wait_reports_host_and_seconds():
    waits = []
    call_with_retry(flaky(r429("7")), "api.x", sleep=lambda s: None, on_wait=lambda h, s: waits.append((h, s)))
    assert waits == [("api.x", 7)]


def test_long_retry_after_is_error_without_sleep():
    slept = []
    with pytest.raises(AppError, match="10 мин") as ei:
        call_with_retry(flaky(r429("600")), "api.x", sleep=slept.append)
    assert "api.x" in str(ei.value) and slept == []


def test_gives_up_after_tries():
    slept = []
    with pytest.raises(AppError, match="Превышен лимит"):
        call_with_retry(flaky(*[r429("1")] * 5), "h", sleep=slept.append)
    assert len(slept) == 4


def masked_5xx():  # what spotipy raises when its own retries on a 5xx run out
    return SpotifyException(429, -1, "/v1/x:\n Max Retries")


def test_masked_5xx_write_is_not_repeated():
    slept = []
    with pytest.raises(AppError, match="api.x временно недоступен") as ei:
        call_with_retry(flaky(masked_5xx()), "api.x", sleep=slept.append, write=True)
    assert "лимит" not in str(ei.value) and slept == []


def test_masked_5xx_read_retries_then_says_unavailable():
    slept = []
    assert call_with_retry(flaky(masked_5xx()), "h", sleep=slept.append) == "ok" and slept == [5]
    slept.clear()
    with pytest.raises(AppError, match="временно недоступен"):
        call_with_retry(flaky(*[masked_5xx()] * 5), "h", sleep=slept.append)
    assert len(slept) == 4


def test_real_429_write_is_still_waited_out():
    slept = []
    assert call_with_retry(flaky(r429("3")), "h", sleep=slept.append, write=True) == "ok" and slept == [3]


def conn_error(url):
    return requests.ConnectionError(request=requests.Request("GET", url).prepare())


def test_connection_error_names_host_from_request():
    with pytest.raises(AppError, match="accounts.spotify.com"):
        call_with_retry(flaky(conn_error("https://accounts.spotify.com/api/token")), "api.spotify.com")


def test_connection_error_without_request_uses_host_arg():
    with pytest.raises(AppError, match="api.spotify.com"):
        call_with_retry(flaky(requests.ConnectionError()), "api.spotify.com")


def test_yandex_network_error_from_connection_error():
    try:
        try:
            raise conn_error("https://api.music.yandex.net/account/status")
        except requests.RequestException as e:
            raise NetworkError(e) from e
    except NetworkError as e:
        err = e
    with pytest.raises(AppError, match="api.music.yandex.net"):
        call_with_retry(flaky(err), "h")


def test_timeout_says_no_response():
    try:
        try:
            raise requests.ReadTimeout(request=requests.Request("GET", "https://api.music.yandex.net/x").prepare())
        except requests.RequestException as e:
            raise TimedOutError() from e
    except TimedOutError as e:
        err = e
    with pytest.raises(AppError, match="Нет ответа от api.music.yandex.net"):
        call_with_retry(flaky(err), "h")


def test_other_errors_pass_through():
    with pytest.raises(ValueError):
        call_with_retry(flaky(ValueError("x")), "h")


def test_load_config(tmp_path):
    assert load_config(tmp_path / "none.json") == {}
    (tmp_path / "ok.json").write_text('{"spotify_client_id": "abc"}', encoding="utf-8")
    assert load_config(tmp_path / "ok.json") == {"spotify_client_id": "abc"}
    (tmp_path / "bad.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(AppError, match="config.json повреждён"):
        load_config(tmp_path / "bad.json")
    (tmp_path / "list.json").write_text("[]", encoding="utf-8")
    with pytest.raises(AppError, match="нужен объект"):
        load_config(tmp_path / "list.json")


def test_save_config_keeps_other_keys_and_creates_file(tmp_path):
    p = tmp_path / "c.json"
    save_config({"spotify_client_id": "a"}, p)
    p.write_text('{"spotify_client_id": "", "other": 1}', encoding="utf-8")
    save_config({"spotify_client_id": "b"}, p)
    assert load_config(p) == {"spotify_client_id": "b", "other": 1}
    with pytest.raises(AppError, match="Не удалось сохранить"):
        save_config({"x": 1}, tmp_path / "missing" / "c.json")
