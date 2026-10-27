import re
from pathlib import Path

from music_transfer import theme


def test_stylesheet_icons_exist():
    urls = re.findall(r'url\("([^"]+)"\)', theme.QSS.replace("@ASSETS", theme.ASSETS.as_posix()))
    assert len(urls) == 2 and all(Path(u).is_file() for u in urls)
