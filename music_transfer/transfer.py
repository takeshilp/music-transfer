import csv
from dataclasses import dataclass, field

from .common import AppError, Track
from .matching import dedup, find_match

_noop = lambda done, total: None  # progress(done, total) runs in the worker thread


@dataclass
class Job:
    name: str  # name of the new target playlist
    tracks: list[Track]  # source tracks, in order
    dedup: bool = False  # merged mode: also dedup by target id when writing
    results: list[tuple[Track, Track | None, str]] = field(default_factory=list)  # (src, found, "ISRC"|"поиск"|"")
    added: int | None = None  # set by write_jobs

    def not_found(self) -> list[Track]:
        return [s for s, f, _ in self.results if f is None]


def track_key(t):
    return t.id or f"{'|'.join(t.artists)}|{t.title}"


def build_jobs(source, playlists, merged_name=None, progress=_noop):
    per = []
    for i, p in enumerate(playlists):
        per.append((p, source.tracks(p)))
        progress(i + 1, len(playlists))
    if merged_name is None:
        return [Job(p.name, tracks) for p, tracks in per]
    return [Job(merged_name, dedup([t for _, ts in per for t in ts], track_key), dedup=True)]


def match_jobs(jobs, target, progress=_noop):
    cache, done, total = {}, 0, sum(len(j.tracks) for j in jobs)  # a track repeated across playlists is searched once
    for job in jobs:
        job.results = []
        for t in job.tracks:
            k = track_key(t)
            if k not in cache:
                cache[k] = find_match(t, target)
            found, how = cache[k] or (None, "")
            job.results.append((t, found, how))
            done += 1
            progress(done, total)


def copy_jobs(jobs):
    """Same service, another account: every playable track is its own match, nothing is searched."""
    for job in jobs:
        job.results = [(t, t if t.id and t.available else None, "копия") for t in job.tracks]


def write_jobs(jobs, target, progress=_noop, private=False):
    """create_playlist is the only write here (the GUI also follows playlists): existing ones are never touched."""
    for i, job in enumerate(jobs):
        if job.added is not None:  # written by an earlier run that failed later: do not create it twice
            continue
        found =[f for _, f, _ in job.results if f]
        if job.dedup:
            found = dedup(found, lambda t: t.id)
        try:
            target.create_playlist(job.name, found, private=private)
        except Exception as e:
            raise AppError(f"Плейлист «{job.name}»: {e} Готово плейлистов: {i} из {len(jobs)}; "
                           "этот мог создаться частично.") from e
        job.added = len(found)
        progress(i + 1, len(jobs))


def _cell(s):
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s  # titles come from public catalogs: no spreadsheet formulas


def export_csv(path, jobs):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Плейлист", "Исполнитель", "Название", "Альбом", "Длительность", "ISRC"])
        for job in jobs:
            for t in job.not_found():
                m, s = divmod(t.duration_ms // 1000, 60)
                w.writerow([_cell(x) for x in (job.name, ", ".join(t.artists), t.title, t.album, f"{m}:{s:02d}", t.isrc or "")])
