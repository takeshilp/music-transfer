import re, unicodedata

# Normalization is for comparison and search only, never for display.
# shortcut: accents are not folded, "&" vs "and" is not unified, only the primary artist is compared,
# Russian keep words (ремикс, концерт) are missing; upgrade if the live check shows misses.
FEAT_SEG = re.compile(r"^(feat|ft|featuring|with|при\s+уч|при\s+участии)\b")
FEAT_TAIL = re.compile(r"\s(feat\.|ft\.|featuring|при\s+уч\.|при\s+участии)\s.*$")
BRACKET = re.compile(r"\(([^()\[\]]*)\)|\[([^()\[\]]*)\]")
DASH = re.compile(r"\s+[-–—]\s+")
KEEP = re.compile(r"\b(live|remix|remixed|acoustic|instrumental|radio edit|sped up|slowed)\b")
EDITION = {"remaster", "remastered", "remastering", "digital", "digitally", "deluxe", "edition", "version",
           "mono", "stereo", "anniversary", "expanded", "bonus", "track", "single", "album", "ремастер", "ремастеринг"}
NUMBER = re.compile(r"^((19|20)\d\d|\d+(st|nd|rd|th))$")  # years, "25th"
TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya"})


def _lower(s):
    return unicodedata.normalize("NFKC", s).lower().replace("ё", "е")


def _clean(s):
    return re.sub(r"[\W_]+", " ", re.sub(r"['’`ʼ]", "", _lower(s))).strip()


def strip_tags(s):
    """Lowercase, feat and edition parts removed, punctuation kept: the search query."""
    orig = s = _lower(s)
    segs = []
    while m := BRACKET.search(s):
        segs.append(m.group(1) if m.group(1) is not None else m.group(2))
        s = s[:m.start()] + " " + s[m.end():]
    base, *dashed = DASH.split(s)
    base = FEAT_TAIL.sub("", base)
    kept = []
    for seg in segs + dashed:
        toks = _clean(seg).split()
        text = " ".join(toks)
        if not toks or FEAT_SEG.match(text):
            continue
        if KEEP.search(text):
            kept.append(" ".join(t for t in toks if t not in EDITION and not NUMBER.match(t)))
        elif not all(t in EDITION or NUMBER.match(t) for t in toks):
            kept.append(seg.strip())
    return " ".join([base.strip()] + kept).strip() or orig


def normalize(s):
    return _clean(strip_tags(s))


def artist_key(a):
    return _clean(a).translate(TRANSLIT)


def dedup(items, key):
    seen = set()
    return [x for x in items if not (key(x) in seen or seen.add(key(x)))]


def _isrc(t):
    return (t.isrc or "").replace("-", "").strip().upper()


def find_match(src, target):
    """Best target track for src as (track, "ISRC"|"поиск"), or None."""
    if _isrc(src):
        for c in target.search_isrc(_isrc(src)):
            if c.available and _isrc(c) == _isrc(src):
                return c, "ISRC"
    if not src.artists or not src.title:
        return None
    cands = [c for c in target.search(src.artists[0], strip_tags(src.title)) if c.available]
    if _isrc(src):  # Yandex target: search_isrc is empty, ISRC comes with the text search
        for c in cands:
            if _isrc(c) == _isrc(src):
                return c, "ISRC"
    delta = lambda c: abs((c.duration_ms or 0) - (src.duration_ms or 0))
    ok = [c for c in cands if c.artists and normalize(c.title) == normalize(src.title)
          and artist_key(c.artists[0]) == artist_key(src.artists[0]) and delta(c) <= 5000]
    return (min(ok, key=delta), "поиск") if ok else None
