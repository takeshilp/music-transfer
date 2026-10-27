"""Updates from the public GitHub repository: the latest release's setup.exe, checked and run silently."""
import hashlib, re, subprocess, tempfile
from pathlib import Path

import requests

from . import __version__
from .common import AppError, call_with_retry

REPO = "menemegod/music-transfer"  # release.ps1 stops if the logged-in GitHub account does not own it
API_HOST = "api.github.com"
LATEST = f"https://{API_HOST}/repos/{REPO}/releases/latest"
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"  # only our own release files are ever run
ASSET = re.compile(r"MusicTransfer-Setup-[\d.]+\.exe")


def version(text):
    """'v0.10.2' -> (0, 10, 2), so versions compare as numbers."""
    return tuple(int(x) for x in re.findall(r"\d+", text))


def latest():
    """The newest release as (version, installer asset)."""
    r = call_with_retry(lambda: requests.get(LATEST, timeout=15, headers={"Accept": "application/vnd.github+json"}),
                        API_HOST)
    if r.status_code == 404:
        raise AppError("В репозитории программы пока нет выпусков")
    if not r.ok:
        raise AppError(f"GitHub не ответил на проверку обновлений ({r.status_code}). Повторите позже.")
    data = r.json()
    asset = next((a for a in data.get("assets") or [] if ASSET.fullmatch(a.get("name", ""))), None)
    if not asset or not asset.get("browser_download_url", "").startswith(DOWNLOADS):
        raise AppError("В последнем выпуске нет установщика программы")
    return data["tag_name"].lstrip("v"), asset


def is_newer(v):
    return version(v) > version(__version__)


def download(asset, progress=lambda done, total: None):
    """Saves the installer to %TEMP% and checks its size and, when GitHub gives one, its SHA-256."""
    path, digest, done = Path(tempfile.gettempdir()) / asset["name"], hashlib.sha256(), 0
    try:
        with requests.get(asset["browser_download_url"], stream=True, timeout=30) as r:
            if not r.ok:
                raise AppError(f"Не удалось скачать обновление ({r.status_code}). Повторите позже.")
            with open(path, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    progress(done, asset["size"])
    except requests.RequestException as e:
        path.unlink(missing_ok=True)
        raise AppError("Обновление не скачалось: проверьте интернет или прокси") from e
    got = "sha256:" + digest.hexdigest()
    if done != asset["size"] or asset.get("digest", got) != got:  # GitHub gives "digest" for files uploaded since 2025
        path.unlink(missing_ok=True)
        raise AppError("Скачанный установщик повреждён. Повторите проверку обновлений.")
    return path


def install(path):
    """Runs the installer without windows; it closes this app if still open, updates it and starts it again
    (installer.iss: /UPDATE=1). The caller quits right after."""
    subprocess.Popen([str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/UPDATE=1"])
