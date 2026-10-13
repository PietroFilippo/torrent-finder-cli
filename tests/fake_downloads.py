"""A job manager without aria2c, for the screens that read one: tests and the UI snapshots.

``FakeManager`` keeps the engine's public shape (snapshot, active, summary,
mark_seen, stop, remove, clear_finished, enqueue_aria2, batch, is_busy,
shutdown, revision, on_change) over a list of real ``Job`` records, and
``sample_jobs`` is the set the approved mock-ups show: every state, with
fixed times so a capture is the same in every theme and run. ``install``
makes it the session's manager for one test.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from unittest.mock import patch

from torrent_finder import downloads
from torrent_finder.downloads import ACTIVE_STATES, FINISHED_STATES, DuplicateDownloadError, Job, Summary

LOG = r"C:\Users\you\AppData\Local\torrent-finder\aria2-background.log"
ANIME = r"D:\Torrents\Anime"
MOVIES = r"D:\Torrents\Movies"
MANGA = r"D:\Torrents\Manga"
FRIEREN = "[SubsPlease] Frieren - 01 (1080p)"
GIB = 1024 ** 3


def at(hour: int, minute: int) -> float:
    """A fixed wall-clock moment on 2026-10-13, in the machine's own time zone."""
    return time.mktime((2026, 10, 13, hour, minute, 0, 0, 0, -1))


def _job(number: int, title: str, state: str, **fields) -> Job:
    base = dict(source="Nyaa", provider_slug="anime", method="aria", target_dir=ANIME,
                magnet=f"magnet:?xt=urn:btih:{number:040x}", log_path=LOG, created_at=at(14, 0))
    base.update(fields)
    job = Job(f"job{number}", title, **base)
    job.state = state
    return job


def sample_jobs() -> list[Job]:
    """The mock-ups' seven downloads: running, fetching metadata, queued, two done, failed, stopped."""
    return [
        _job(1, FRIEREN, "running", done_bytes=int(0.43 * 1.4 * GIB), total_bytes=int(1.4 * GIB),
             speed_bps=int(3.1 * 1024 ** 2), eta_s=4 * 60, peers=14, seeds=3, started_at=at(14, 2), select=(1,)),
        _job(2, "Dune Part Two 2024 2160p REMUX", "metadata", target_dir=MOVIES, provider_slug="movies",
             source="Knaben", peers=3, started_at=at(14, 5)),
        _job(3, "The Expanse S04 1080p", "queued", target_dir=MOVIES, provider_slug="movies", source="Apibay",
             select=tuple(range(1, 11)), created_at=at(14, 6)),
        _job(4, "[SubsPlease] Frieren - 02 (1080p)", "done", done_bytes=int(1.4 * GIB), total_bytes=int(1.4 * GIB),
             started_at=at(13, 39), finished_at=at(13, 48),
             files=(ANIME + "\\[SubsPlease] Frieren - 02 (1080p).mkv",)),
        _job(5, "Berserk v01-v41 (Dark Horse)", "done", target_dir=MANGA, provider_slug="manga",
             done_bytes=int(3.2 * GIB), total_bytes=int(3.2 * GIB), started_at=at(12, 5), finished_at=at(12, 30),
             files=tuple(f"{MANGA}\\Berserk\\Berserk v{n:02d}.cbz" for n in range(1, 42)),
             notes=("Unpacked into " + MANGA + "\\Berserk\\Berserk v01", "Unpacked into " + MANGA + "\\Berserk\\Berserk v02")),
        _job(6, "Blue Giant 2023 1080p", "failed", target_dir=MOVIES, provider_slug="movies", source="Apibay",
             error="aria2c download failed: Download aborted. URI=magnet:?xt=urn:btih:3f9a…",
             notes=("aria2c log: [ERROR] Download aborted. URI=magnet:?xt=urn:btih:3f9a…\n"
                    "errorCode=29  Resource temporarily unavailable (no peers for 10 minutes)",),
             started_at=at(13, 21), finished_at=at(13, 31)),
        _job(7, "One Piece 1090 (1080p)", "stopped", done_bytes=int(0.61 * 1.1 * GIB), total_bytes=int(1.1 * GIB),
             started_at=at(12, 58), finished_at=at(13, 12)),
    ]


class FakeManager:
    """The engine's reading and acting surface over in-memory jobs; nothing runs."""

    def __init__(self, jobs=()):
        self._jobs: dict[str, Job] = {job.id: job for job in jobs}
        self.revision = 1
        self._seen: set[str] = set()
        self.calls: list = []
        self.on_change: list = []
        self.closed = False

    # reading
    def snapshot(self) -> tuple:
        return tuple(downloads._copy(job) for job in self._jobs.values())

    def active(self) -> tuple:
        return tuple(job for job in self.snapshot() if job.state in ACTIVE_STATES)

    def summary(self) -> Summary:
        jobs = [job for job in self._jobs.values() if job.state in ACTIVE_STATES]
        progress = [job.progress for job in jobs if job.progress is not None]
        unseen = sum(job.state == "done" and job.id not in self._seen for job in self._jobs.values())
        return Summary(len(jobs), max(progress, default=None), sum(job.speed_bps for job in jobs), unseen)

    def is_busy(self) -> bool:
        return any(job.state in ACTIVE_STATES for job in self._jobs.values())

    def job(self, job_id: str) -> Job:
        return self._jobs[job_id]

    # changing
    def bump(self) -> None:
        self.revision += 1
        for hook in self.on_change:
            hook()

    def set_state(self, job_id: str, state: str, **fields) -> None:
        job = self._jobs[job_id]
        job.state = state
        for name, value in fields.items():
            setattr(job, name, value)
        if state in FINISHED_STATES and job.finished_at is None:
            job.finished_at = time.time()
        self.bump()

    def mark_seen(self) -> None:
        self.calls.append(("mark_seen",))
        done = {job.id for job in self._jobs.values() if job.state == "done"}
        if not done.issubset(self._seen):
            self._seen.update(done)
            self.bump()

    def stop(self, job_id: str) -> None:
        self.calls.append(("stop", job_id))
        if self._jobs[job_id].state in ACTIVE_STATES:
            self.set_state(job_id, "stopped", speed_bps=0, eta_s=None)

    def remove(self, job_id: str) -> None:
        self.calls.append(("remove", job_id))
        if self._jobs[job_id].state in ACTIVE_STATES:
            raise ValueError("Stop the download before removing it.")
        del self._jobs[job_id]
        self.bump()

    def clear_finished(self) -> None:
        self.calls.append(("clear_finished",))
        for job_id in [job.id for job in self._jobs.values() if job.state in FINISHED_STATES]:
            del self._jobs[job_id]
        self.bump()

    def enqueue_aria2(self, title, magnet, select=None, *, source, provider_slug, method, group=None) -> Job:
        self.calls.append(("enqueue", title, magnet, select, source, provider_slug, method, group))
        if self.closed:
            raise RuntimeError("The background download manager is closed.")
        if any(job.magnet == magnet and job.state in ACTIVE_STATES for job in self._jobs.values()):
            raise DuplicateDownloadError("This torrent and file selection are already downloading to this folder.")
        job = Job(f"job{len(self._jobs) + 100}", title, source, provider_slug, method, ANIME, magnet,
                  select=tuple(select) if select else None, group=group, log_path=LOG)
        self._jobs[job.id] = job
        self.bump()
        return downloads._copy(job)

    @contextmanager
    def batch(self):
        self.calls.append(("batch",))
        yield self

    def shutdown(self, graceful: bool = True) -> None:
        self.calls.append(("shutdown", graceful))
        self.closed = True
        for job in self._jobs.values():
            if job.state in ACTIVE_STATES:
                job.state = "stopped"
        self.bump()


def install(case, manager: "FakeManager | None") -> "FakeManager | None":
    """Make *manager* the session's manager for one test; None means no download was started."""
    patcher = patch.object(downloads, "_manager", manager)
    patcher.start()
    case.addCleanup(patcher.stop)
    from torrent_finder.ui import downloads as downloads_ui
    announced = set(downloads_ui._announced)
    downloads_ui._announced.clear()
    case.addCleanup(lambda: (downloads_ui._announced.clear(), downloads_ui._announced.update(announced)))
    return manager
