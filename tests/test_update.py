import hashlib

import pytest

from music_transfer import update
from music_transfer.common import AppError

BODY = b"setup" * 1000
URL = update.DOWNLOADS + "v9.9.9/MusicTransfer-Setup-9.9.9.exe"


class Resp:
    def __init__(self, status=200, data=None, body=b""):
        self.status_code, self.ok, self._data, self._body = status, status < 400, data, body

    def json(self):
        return self._data

    def iter_content(self, size):
        return (self._body[i:i + size] for i in range(0, len(self._body), size))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def asset(**kw):
    return {"name": "MusicTransfer-Setup-9.9.9.exe", "browser_download_url": URL, "size": len(BODY),
            "digest": "sha256:" + hashlib.sha256(BODY).hexdigest(), **kw}


def test_versions_compare_as_numbers():
    assert update.version("v0.10.0") > update.version("0.9.9") and update.is_newer("999.0.0")
    assert not update.is_newer(update.__version__)


def test_latest_finds_our_installer(monkeypatch):
    other = {"name": "notes.txt", "browser_download_url": update.DOWNLOADS + "x"}
    monkeypatch.setattr(update.requests, "get", lambda *a, **k: Resp(data={"tag_name": "v9.9.9", "assets": [other, asset()]}))
    assert update.latest() == ("9.9.9", asset())


@pytest.mark.parametrize("resp, text", [
    (Resp(404), "нет выпусков"),
    (Resp(403), "403"),
    (Resp(data={"tag_name": "v9", "assets": []}), "нет установщика"),
    (Resp(data={"tag_name": "v9", "assets": [asset(browser_download_url="https://evil.example/MusicTransfer-Setup-9.exe")]}),
     "нет установщика"),  # only files of our own releases are ever run
])
def test_latest_refuses(monkeypatch, resp, text):
    monkeypatch.setattr(update.requests, "get", lambda *a, **k: resp)
    with pytest.raises(AppError, match=text):
        update.latest()


def test_cleanup_removes_only_our_old_installers(monkeypatch, tmp_path):
    monkeypatch.setattr(update.tempfile, "gettempdir", lambda: str(tmp_path))
    ours, other = tmp_path / "MusicTransfer-Setup-0.2.1.exe", tmp_path / "other-setup.exe"
    ours.write_bytes(b"x")
    other.write_bytes(b"x")
    update.cleanup()
    assert not ours.exists() and other.exists()


def test_download_checks_size_and_sha256(monkeypatch, tmp_path):
    monkeypatch.setattr(update.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(update.requests, "get", lambda *a, **k: Resp(body=BODY))
    seen = []
    path = update.download(asset(), lambda d, n: seen.append((d, n)))
    assert path.read_bytes() == BODY and seen[-1] == (len(BODY), len(BODY))
    for bad in (asset(digest="sha256:" + "0" * 64), asset(size=len(BODY) + 1)):
        with pytest.raises(AppError, match="повреждён"):
            update.download(bad)
        assert not path.exists()
    no_digest = asset()
    del no_digest["digest"]  # releases uploaded before GitHub added digests: the size check still holds
    assert update.download(no_digest) == path
