import pytest

from music_transfer.common import Track
from music_transfer.matching import artist_key, dedup, find_match, normalize, strip_tags


@pytest.mark.parametrize("raw, want", [
    ("Song (feat. X) [Remastered 2011]", "song"),
    ("Ёлки - 2009 Remaster", "елки"),
    ("Song - Live", "song live"),
    ("Song (Radio Edit)", "song radio edit"),
    ("Song (Live at Wembley 1986) [2011 Remaster]", "song live at wembley"),
    ("Song feat. X", "song"),
    ("Song (ft. X)", "song"),
    ("Song [Featuring X]", "song"),
    ("Song (при уч. Иван)", "song"),
    ("Song (with X)", "song"),
    ("Don't Stop", "dont stop"),
    ("Jay-Z", "jay z"),
    ("(Intro)", "intro"),
    ("Всё идёт", "все идет"),
    ("Song (Part 2)", "song part 2"),
])
def test_normalize(raw, want):
    assert normalize(raw) == want


def test_strip_tags_keeps_punctuation():
    assert strip_tags("P.I.M.P. (feat. X)") == "p.i.m.p."


def test_strip_tags_empty_base_falls_back_to_original():
    assert strip_tags("[Remastered]") == "[remastered]"


def test_artist_key_translit():
    assert artist_key("Кино") == artist_key("Kino") == "kino"
    assert artist_key("Мумий Тролль") == "mumiy troll"


def test_dedup_keeps_first():
    assert dedup([1, 2, 1, 3, 2], lambda x: x) == [1, 2, 3]


class FakeTarget:
    def __init__(self, found=(), by_isrc=()):
        self.found, self.by_isrc, self.searches = list(found), list(by_isrc), []

    def search(self, artist, title):
        self.searches.append((artist, title))
        return self.found

    def search_isrc(self, isrc):
        return self.by_isrc


def T(title="Song", artist="Artist", ms=200000, isrc=None, available=True, id="1"):
    return Track(id, title, [artist], ms, isrc, available)


def test_duration_tolerance_boundary():
    assert find_match(T(), FakeTarget([T(ms=205000)])) is not None
    assert find_match(T(), FakeTarget([T(ms=205001)])) is None


def test_text_match_reports_search():
    assert find_match(T(), FakeTarget([T(id="9")]))[1] == "поиск"


def test_isrc_candidate_beats_text_match():
    src = T(isrc="US-ABC-1")
    good, perfect_text = T(id="isrc", title="Other", ms=1, isrc="USABC1"), T(id="text")
    track, how = find_match(src, FakeTarget([perfect_text, good]))
    assert (track.id, how) == ("isrc", "ISRC")


def test_search_isrc_skips_unavailable():
    src = T(isrc="X1")
    t = FakeTarget(by_isrc=[T(id="a", isrc="X1", available=False), T(id="b", isrc="x1")])
    assert find_match(src, t)[0].id == "b"


def test_live_never_matches_studio():
    assert find_match(T("Song - Live"), FakeTarget([T("Song")])) is None


def test_only_unavailable_candidates():
    assert find_match(T(), FakeTarget([T(available=False)])) is None


def test_closest_duration_wins_and_tie_keeps_first():
    src = T(ms=200000)
    assert find_match(src, FakeTarget([T(id="far", ms=204000), T(id="near", ms=201000)]))[0].id == "near"
    assert find_match(src, FakeTarget([T(id="a", ms=201000), T(id="b", ms=199000)]))[0].id == "a"


def test_no_artists_means_no_search():
    t = FakeTarget([T()])
    assert find_match(Track("1", "Song", [], 1000), t) is None
    assert t.searches == []


def test_search_query_is_stripped_title():
    t = FakeTarget()
    find_match(T("Song (feat. X) [Remastered 2011]"), t)
    assert t.searches == [("Artist", "song")]
