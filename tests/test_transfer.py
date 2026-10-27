import pytest

from music_transfer.common import AppError, Playlist, Track
from music_transfer.transfer import Job, build_jobs, copy_jobs, export_csv, match_jobs, write_jobs


def T(id, title=None, artist="A", **kw):
    return Track(id, title or f"Song {id}", [artist], 200000, **kw)


class Source:
    def __init__(self, data):
        self.data = data

    def tracks(self, p):
        return self.data[p.id]


class Target:
    """Finds a track 'tN' as target id 'xN'; ids listed in missing are not found."""
    def __init__(self, missing=(), same=None, fail_on=None):
        self.missing, self.same, self.fail_on = set(missing), same or {}, fail_on
        self.searches, self.created = 0, []

    def search_isrc(self, isrc):
        return []

    def search(self, artist, title):
        self.searches += 1
        n = title.split()[-1]
        if n in self.missing:
            return []
        return [Track(self.same.get(n, "x" + n), f"Song {n}", [artist], 200000)]

    def create_playlist(self, name, tracks):
        if self.fail_on == len(self.created) + 1:
            raise RuntimeError("boom")
        self.created.append((name, [t.id for t in tracks]))


PL = [Playlist("a", "A", 0), Playlist("b", "B", 0)]


def test_copy_jobs_keeps_playable_tracks_as_they_are_and_searches_nothing():
    local, gone = T(None, "Local file"), T("t3", available=False)
    jobs = build_jobs(Source({"a": [T("t1"), local, gone, T("t2")]}), PL[:1])
    copy_jobs(jobs)
    target = Target()
    write_jobs(jobs, target)
    assert [how for _, _, how in jobs[0].results] == ["копия"] * 4 and jobs[0].not_found() == [local, gone]
    assert target.created == [("A", ["t1", "t2"])] and target.searches == 0


def run(data, playlists, target, merged=None):
    jobs = build_jobs(Source(data), playlists, merged)
    match_jobs(jobs, target)
    write_jobs(jobs, target)
    return jobs


def test_per_playlist_creates_one_each_in_order_skipping_not_found():
    t = Target(missing={"t2"})
    run({"a": [T("t1"), T("t2"), T("t3")], "b": [T("t4")]}, PL, t)
    assert t.created == [("A", ["xt1", "xt3"]), ("B", ["xt4"])]


def test_all_not_found_playlist_still_created_empty():
    t = Target(missing={"t1"})
    jobs = run({"a": [T("t1")], "b": [T("t4")]}, PL, t)
    assert t.created[0] == ("A", []) and jobs[0].added == 0


def test_merged_keeps_source_order_and_dedups():
    t = Target(same={"t4": "xt3"})
    run({"a": [T("t1"), T("t2"), T("t3")], "b": [T("t2"), T("t4")]}, PL, t, merged="All")
    assert t.created == [("All", ["xt1", "xt2", "xt3"])]


def test_repeated_track_searched_once_and_progress_ends_at_total():
    t, seen = Target(), []
    jobs = build_jobs(Source({"a": [T("t1")], "b": [T("t1"), T("t2")]}), PL)
    match_jobs(jobs, t, progress=lambda d, n: seen.append((d, n)))
    assert t.searches == 2 and seen[-1] == (3, 3)


def test_failed_create_names_playlist_and_progress():
    t = Target(fail_on=2)
    with pytest.raises(AppError, match="«B».*1 из 2"):
        run({"a": [T("t1")], "b": [T("t2")]}, PL, t)


def test_rerun_after_failure_skips_written_playlists():
    t = Target(fail_on=2)
    jobs = build_jobs(Source({"a": [T("t1")], "b": [T("t2")]}), PL)
    match_jobs(jobs, t)
    with pytest.raises(AppError):
        write_jobs(jobs, t)
    t.fail_on = None
    write_jobs(jobs, t)
    assert [n for n, _ in t.created] == ["A", "B"]


def test_csv_bom_semicolon_header_and_formula_guard(tmp_path):
    job = Job("Мой", [T("t1", title="=cmd", artist="Кино")])
    job.results = [(job.tracks[0], None, "")]
    p = tmp_path / "nf.csv"
    export_csv(p, [job])
    raw = p.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    lines = raw.decode("utf-8-sig").splitlines()
    assert lines[0] == "Плейлист;Исполнитель;Название;Альбом;Длительность;ISRC"
    assert lines[1] == "Мой;Кино;'=cmd;;3:20;"
