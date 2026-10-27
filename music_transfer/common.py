import json, os, sys, time
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from urllib.parse import urlparse

import requests
from yandex_music.exceptions import NetworkError

APP_DIR = Path(os.environ["APPDATA"]) / "music-transfer"  # tokens only here
APP_ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_ROOT / "config.json"
LIKED = "liked"  # Playlist.id of the liked collection on both services
TRIES, DEFAULT_WAIT, MAX_WAIT = 5, 5, 300


@dataclass
class Track:
    id: str | None  # None: Spotify local file
    title: str  # display title (Yandex: "title (version)")
    artists: list[str]  # primary first
    duration_ms: int = 0
    isrc: str | None = None
    available: bool = True  # playable on that service and writable (Yandex: has album_id)
    album: str = ""
    album_id: str | None = None  # Yandex only, needed to insert


@dataclass
class Playlist:
    id: str
    name: str
    count: int
    followed: bool = False  # someone else's playlist the account subscribes to: can be followed, not copied


class AppError(Exception):
    """Message is Russian and shown to the user as is."""


def load_config(path=CONFIG_PATH) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as e:
        raise AppError(f"config.json повреждён: {e}") from e
    if not isinstance(data, dict):
        raise AppError('config.json повреждён: нужен объект вида {"spotify_client_id": "..."}')
    return data


def save_config(changes, path=CONFIG_PATH):
    """Merge changes into config.json, keeping the other keys."""
    data = {**load_config(path), **changes}
    try:
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as e:
        raise AppError(f"Не удалось сохранить {path}: {e}") from e


class Cancelled(Exception):
    """«Отмена» was pressed: the run stops at its next read, 429 wait or progress step. Not an error."""


def _retry_after(e):
    """Seconds to wait if e is a rate limit, else None."""
    if getattr(e, "http_status", None) == 429:  # SpotifyException
        try:
            return float((e.headers or {}).get("Retry-After"))
        except (TypeError, ValueError):
            return DEFAULT_WAIT
    if isinstance(e, NetworkError) and "(429)" in str(e):  # the library keeps no headers
        return DEFAULT_WAIT


def call_with_retry(fn, host, sleep=time.sleep, on_wait=None, write=False, stop=None):
    """Run fn, waiting out 429s (on_wait(host, seconds) is told before each wait); network errors become AppError.

    write=True: a write is never repeated after a masked 5xx, it could create a duplicate.
    stop (threading.Event): once set, a read raises Cancelled before its next try and a 429 wait ends at once;
    a write ignores it, so «Отмена» never leaves a playlist half-written."""
    stop = None if write else stop
    for attempt in range(TRIES):
        if stop and stop.is_set():
            raise Cancelled()
        try:
            return fn()
        except Exception as e:
            wait = _retry_after(e)
            # spotipy turns exhausted 5xx retries into a headerless 429 "Max Retries": a server error, not a limit
            if wait is not None and getattr(e, "http_status", None) == 429 and "Max Retries" in str(e.msg) \
                    and (write or attempt == TRIES - 1):
                raise AppError(f"Сервер {host} временно недоступен (ошибка сервера). Повторите позже.") from e
            if wait is None:
                cause = e if isinstance(e, requests.RequestException) else e.__cause__
                if isinstance(cause, requests.RequestException) and not isinstance(cause, requests.HTTPError):
                    req = getattr(cause, "request", None)
                    h = (urlparse(req.url).hostname if req is not None else None) or host
                    if isinstance(cause, requests.Timeout):
                        raise AppError(f"Нет ответа от {h}. Проверьте интернет или прокси.") from e
                    raise AppError(f"Не удалось подключиться к {h}. Проверьте интернет или прокси.") from e
                raise
            if wait > MAX_WAIT or attempt == TRIES - 1:
                raise AppError(f"Превышен лимит запросов {host}, повторите через {max(1, ceil(wait / 60))} мин.") from e
            if on_wait:
                on_wait(host, wait)
            if stop:
                stop.wait(wait)  # returns at once on «Отмена»; the next try raises Cancelled
            else:
                sleep(wait)
