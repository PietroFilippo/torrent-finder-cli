"""In-memory background jobs. Workers never draw, print, or read keys.

Two kinds: aria2c jobs (torrents, followed over aria2's RPC) and direct jobs
(a library file streamed over HTTP: Madokami, Libgen, F-Droid), each run by
its ``fetch`` on a small worker pool. Both finish through the same finisher
(unpacking, statistics) and show in the same Downloads screen.

Hooks receive no arguments, run outside the job lock on the changing thread,
and should only signal the UI to redraw. Returned jobs are independent copies.
"""

# i18n: converted
import base64
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import os
import queue
import threading
import time
from typing import Callable
from urllib.parse import parse_qs, urlparse
import uuid

from torrent_finder import stats, unpack
from torrent_finder.aria2_rpc import Aria2Engine
from torrent_finder.constants import prepare_download_dir
from torrent_finder.direct_download import Cancelled, _RETRY_DELAYS
from torrent_finder.i18n import N_, t


ACTIVE_STATES = frozenset({"queued", "metadata", "running", "paused", "unpacking"})
FINISHED_STATES = frozenset({"done", "failed", "stopped", "interrupted"})
_LABELS = {
    "queued": N_("queued", ctx="download state"),
    "metadata": N_("fetching metadata", ctx="download state"),
    "running": N_("downloading", ctx="download state"),
    "paused": N_("paused", ctx="download state"),
    "unpacking": N_("unpacking", ctx="download state"),
    "done": N_("completed", ctx="download state"),
    "failed": N_("failed", ctx="download state"),
    "stopped": N_("stopped", ctx="download state"),
    "interrupted": N_("interrupted", ctx="download state"),
}


@dataclass
class Job:
    id: str
    title: str
    source: str
    provider_slug: str
    method: str
    target_dir: str
    magnet: str
    select: tuple[int, ...] | None = None
    group: str | None = None
    backend: str = "aria2c"
    state: str = "queued"
    done_bytes: int = 0
    total_bytes: int = 0
    speed_bps: int = 0
    eta_s: int | None = None
    peers: int = 0
    seeds: int = 0
    files: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    error: str = ""
    log_path: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    gid: str | None = None
    # A direct job: what it downloads, run again by Retry; whether its files are page archives.
    fetch: object = field(default=None, repr=False, compare=False)
    expect_pages: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)
    proc: object = field(default=None, repr=False, compare=False)

    @property
    def state_label(self) -> str:
        return t(_LABELS[self.state])

    @property
    def progress(self) -> float | None:
        """Fraction 0..1, or None while the payload length is unknown."""
        return min(1.0, self.done_bytes / self.total_bytes) if self.total_bytes else None


@dataclass(frozen=True)
class Summary:
    """Status figure: count all unfinished jobs, fractional progress and B/s."""
    running_count: int
    progress: float | None
    speed_bps: int
    unseen_completions: int


class DuplicateDownloadError(ValueError):
    """The same info hash, folder and file selection is already active."""


class DirectDownloadError(Exception):
    """A direct job's fetch failed; the message says why and where to get the file by hand."""


DIRECT_WORKERS = 2  # direct downloads at a time, like aria2c's


def _identity(magnet: str, folder: str, select: tuple[int, ...] | None) -> tuple:
    hashes = parse_qs(urlparse(magnet).query).get("xt", [])
    info_hash = next((value[9:] for value in hashes if value.lower().startswith("urn:btih:")), magnet)
    if len(info_hash) == 32:
        try:
            info_hash = base64.b32decode(info_hash.upper()).hex()
        except ValueError:
            pass
    return info_hash.lower(), os.path.normcase(os.path.realpath(folder)), select


def _copy(job: Job) -> Job:
    event = threading.Event()
    if job.cancel_event.is_set():
        event.set()
    return replace(job, cancel_event=event)


class JobManager:
    def __init__(self, engine: Aria2Engine | None = None):
        self._engine = engine if engine is not None else Aria2Engine()
        self._lock = threading.RLock()
        # Serialize lifecycle operations, including GID handoffs, without I/O
        # under the job-data lock. Readers remain responsive during slow RPC.
        self._operations = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._revision = 0
        self._last_progress = float("-inf")
        self._seen: set[str] = set()
        self._counted_groups: set[tuple[str, str]] = set()
        self._group_states: dict[tuple[str, str], dict[str, str]] = {}
        self._identities: dict[str, tuple] = {}
        self._metadata: set[str] = set()
        self._finishing: set[str] = set()
        self._finish_queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._closed = False
        self._poll_failures = 0
        self._poller: threading.Thread | None = None
        self._finisher: threading.Thread | None = None
        self._direct_queue: queue.Queue = queue.Queue()
        self._direct_workers: list[threading.Thread] = []
        # Set by each direct worker as it really returns: an interrupted join()
        # can report a thread finished while its target still runs (CPython 3.11).
        self._direct_done: list[threading.Event] = []
        # Direct jobs whose fetch has not returned yet, even after Stop marked
        # them: their file may still be open. Busy, not removable, not repeatable.
        self._fetching: set[str] = set()
        self.on_change: list[Callable[[], None]] = []

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def _bump(self, *, progress: bool = False) -> bool:
        # Caller holds _lock. State changes always publish immediately.
        now = time.monotonic()
        if progress and now - self._last_progress < 1:
            return False
        if progress:
            self._last_progress = now
        self._revision += 1
        return True

    def _notify(self) -> None:
        with self._lock:
            hooks = tuple(self.on_change)
        for hook in hooks:
            try:
                hook()
            except Exception:
                pass  # a broken UI subscriber cannot strand downloads

    def enqueue_aria2(self, title: str, magnet: str, select=None, *, source: str,
                      provider_slug: str, method: str, group: str | None = None,
                      folder: str | None = None) -> Job:
        """Queue an aria2c download into *folder*, by default the download folder setting."""
        selection = tuple(select) if select is not None else None
        if selection is not None and (not selection or any(type(i) is not int or i < 1 for i in selection)):
            raise ValueError(t("Select at least one file using 1-based file indexes."))
        if selection is not None:
            selection = tuple(sorted(set(selection)))
        with self._operations:
            with self._lock:
                if self._closed:
                    raise RuntimeError(t("The background download manager is closed."))
            try:
                folder = os.path.abspath(prepare_download_dir(folder))
            except OSError as error:
                raise OSError(t("Could not prepare the download folder: {error}", error=error)) from error
            identity = _identity(magnet, folder, selection)
            with self._lock:
                if any(self._identities[j.id] == identity
                       for j in self._jobs.values() if j.state in ACTIVE_STATES):
                    raise DuplicateDownloadError(t("This torrent and file selection are already downloading to this folder."))
            # Start/add errors propagate to the caller; no phantom queued job.
            gid = self._engine.add_uri(magnet, folder, selection)
            job = Job(uuid.uuid4().hex, title, source, provider_slug, method, folder, magnet,
                      select=selection, group=group, gid=gid, log_path=self._engine.log_path,
                      proc=self._engine.proc)
            with self._lock:
                self._jobs[job.id] = job
                self._identities[job.id] = identity
                if magnet.startswith("magnet:"):
                    self._metadata.add(job.id)
                if group is not None:
                    self._group_states.setdefault((group, method), {})[job.id] = "queued"
                self._bump()
                result = _copy(job)
            self._start_workers()
        self._notify()
        return result

    def _start_workers(self) -> None:
        self._start_finisher()
        if self._poller is not None:
            return
        self._poller = threading.Thread(target=self._poll_loop, name="aria2-poller", daemon=True)
        self._poller.start()

    def _start_finisher(self) -> None:
        if self._finisher is None:
            self._finisher = threading.Thread(target=self._finish_loop, name="download-finisher", daemon=True)
            self._finisher.start()

    def enqueue_direct(self, title: str, fetch, *, key: str, source: str, provider_slug: str,
                       method: str = "direct", folder: str | None = None, group: str | None = None,
                       expect_pages: bool = False) -> Job:
        """Queue a direct download into *folder* (by default the download folder setting).

        ``fetch(cancel_event, progress, note)`` runs on a worker and returns the
        saved paths: ``progress(done, total)`` reports bytes, ``note(text)`` adds
        a line to the job, and *cancel_event* is set by Stop. It raises
        ``DirectDownloadError`` with what to tell the user. *key* identifies the
        file (a library path, a hash): the same key into the same folder is
        refused while it runs. *expect_pages*: page archives, as from Madokami.
        """
        with self._operations:
            with self._lock:
                if self._closed:
                    raise RuntimeError(t("The background download manager is closed."))
            try:
                folder = os.path.abspath(prepare_download_dir(folder))
            except OSError as error:
                raise OSError(t("Could not prepare the download folder: {error}", error=error)) from error
            identity = ("direct", source, key, os.path.normcase(os.path.realpath(folder)))
            with self._lock:
                if any(self._identities[j.id] == identity
                       for j in self._jobs.values() if j.state in ACTIVE_STATES or j.id in self._fetching):
                    raise DuplicateDownloadError(t("This file is already downloading to this folder."))
                # *group* only keeps a batch's rows together: direct jobs count no
                # download method, so they keep no group bookkeeping (_group_states).
                job = Job(uuid.uuid4().hex, title, source, provider_slug, method, folder, key,
                          group=group, backend="direct", fetch=fetch, expect_pages=expect_pages)
                self._jobs[job.id] = job
                self._identities[job.id] = identity
                self._bump()
                result = _copy(job)
            self._start_finisher()
            while len(self._direct_workers) < DIRECT_WORKERS:
                done = threading.Event()
                worker = threading.Thread(target=self._direct_loop, args=(done,), daemon=True,
                                          name=f"direct-download-{len(self._direct_workers) + 1}")
                self._direct_workers.append(worker)
                self._direct_done.append(done)
                worker.start()
            self._direct_queue.put(job.id)
        self._notify()
        return result

    def _direct_loop(self, done: threading.Event) -> None:
        try:
            while True:
                job_id = self._direct_queue.get()
                if job_id is None:
                    return
                try:
                    self._run_direct(job_id)
                except Exception:
                    pass  # _run_direct records failures on the job; never lose the worker
        finally:
            done.set()

    def has_direct(self, source: str, key: str, folder: str) -> bool:
        """Whether this file is downloading (or still being written) to this folder."""
        identity = ("direct", source, key, os.path.normcase(os.path.realpath(os.path.abspath(folder))))
        with self._lock:
            return any(self._identities.get(j.id) == identity
                       for j in self._jobs.values() if j.state in ACTIVE_STATES or j.id in self._fetching)

    def _run_direct(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.cancel_event.is_set() or job.state != "queued":
                return
            job.state = "running"
            job.started_at = job.updated_at = time.time()
            self._fetching.add(job_id)
            self._bump()
        self._notify()
        try:
            self._fetch_direct(job_id, job)
        finally:
            with self._lock:
                self._fetching.discard(job_id)
                self._bump()
            self._notify()

    def _fetch_direct(self, job_id: str, job: Job) -> None:
        sample = [time.monotonic(), 0]

        def progress(done: int, total: "int | None") -> None:
            with self._lock:
                if job.cancel_event.is_set():
                    return
                now = time.monotonic()
                job.done_bytes, job.total_bytes = int(done), int(total or 0)
                if now - sample[0] >= 1:
                    job.speed_bps = max(0, int((done - sample[1]) / (now - sample[0])))
                    sample[:] = [now, done]
                job.eta_s = (max(0, job.total_bytes - job.done_bytes) // job.speed_bps
                             if job.speed_bps and job.total_bytes else None)
                job.updated_at = time.time()
                changed = self._bump(progress=True)
            if changed:
                self._notify()

        error = ""
        try:
            paths = [path for path in (job.fetch(job.cancel_event, progress,
                                                 lambda text: self._note(job_id, text)) or ()) if path]
        except DirectDownloadError as failure:
            paths, error = [], str(failure)
        except Exception as failure:
            paths, error = [], t("Download failed: {error}", error=failure)
        with self._lock:
            if job.cancel_event.is_set():
                if paths:  # Stop came after the file was saved: it is a finished download, not an unfinished one
                    job.files = tuple(paths)
                    job.total_bytes = max(job.total_bytes, job.done_bytes)
                    job.state, job.error = "done", ""
                    job.notes += (t("It finished before it could stop."),)
                    job.updated_at = job.finished_at = time.time()
                    self._bump()
                return  # otherwise Stop has already marked it
            if not paths:
                self._terminal(job, "failed", error or t("Download failed."))
            else:
                job.files = tuple(paths)
                job.total_bytes = max(job.total_bytes, job.done_bytes)
                job.speed_bps, job.eta_s = 0, None
                self._finishing.add(job_id)
                self._bump()
                self._finish_queue.put(job_id)
        self._notify()

    @contextmanager
    def batch(self):
        """Enroll a whole batch before polling any of its members.

        Use a fresh group ID per batch attempt inside this context. Readers
        remain responsive; the operation lock prevents an early completion
        from recording a group before its final member has been enqueued.
        """
        with self._operations:
            yield self

    def snapshot(self) -> tuple[Job, ...]:
        with self._lock:
            return tuple(_copy(j) for j in self._jobs.values())

    def active(self) -> tuple[Job, ...]:
        return tuple(j for j in self.snapshot() if j.state in ACTIVE_STATES)

    def unfinished(self) -> tuple[Job, ...]:
        """What ``is_busy`` waits for: active jobs, and stopped ones still writing or finishing a file."""
        with self._lock:
            return tuple(_copy(j) for j in self._jobs.values()
                         if j.state in ACTIVE_STATES or j.id in self._fetching or j.id in self._finishing)

    def stopping(self, job_id: str) -> bool:
        """A stopped job whose file is still being written or finished."""
        with self._lock:
            job = self._jobs.get(job_id)
            return (job is not None and job.state not in ACTIVE_STATES
                    and (job_id in self._fetching or job_id in self._finishing))

    def summary(self) -> Summary:
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.state in ACTIVE_STATES]
            progress = [j.progress for j in jobs if j.progress is not None]
            unseen = sum(j.state == "done" and j.id not in self._seen for j in self._jobs.values())
            return Summary(len(jobs), max(progress, default=None), sum(j.speed_bps for j in jobs), unseen)

    def mark_seen(self) -> None:
        with self._lock:
            seen = {j.id for j in self._jobs.values() if j.state == "done"}
            changed = not seen.issubset(self._seen)
            self._seen.update(seen)
            if changed:
                self._bump()
        if changed:
            self._notify()

    def _terminal(self, job: Job, state: str, error: str = "") -> None:
        job.state, job.error = state, error
        job.speed_bps, job.eta_s = 0, None
        job.updated_at = job.finished_at = time.time()
        members = self._group_states.get((job.group, job.method)) if job.group is not None else None
        if members is not None:
            members[job.id] = state
        self._bump()

    def stop(self, job_id: str) -> None:
        with self._operations:
            with self._lock:
                job = self._jobs[job_id]
                if job.state not in ACTIVE_STATES:
                    return
                gid = job.gid if job.id not in self._finishing else None
            if gid:
                # Do not claim a successful stop when remove failed; the UI
                # can show the exception and the next poll can resolve it.
                self._engine.remove(gid)
            with self._lock:
                job.cancel_event.set()
                self._terminal(job, "stopped")
        self._notify()

    def remove(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.state in ACTIVE_STATES or job_id in self._finishing or job_id in self._fetching:
                raise ValueError(t("Stop the download before removing it."))
            del self._jobs[job_id]
            self._identities.pop(job_id, None)
            self._metadata.discard(job_id)
            self._seen.discard(job_id)
            self._bump()
        self._notify()

    def clear_finished(self) -> None:
        with self._lock:
            ids = [j.id for j in self._jobs.values()
                   if j.state in FINISHED_STATES and j.id not in self._finishing and j.id not in self._fetching]
            for job_id in ids:
                del self._jobs[job_id]
                self._identities.pop(job_id, None)
                self._metadata.discard(job_id)
                self._seen.discard(job_id)
            if ids:
                self._bump()
        if ids:
            self._notify()

    def _poll_loop(self) -> None:
        while not self._stop.wait(1):
            self._poll_once()

    def _poll_once(self) -> None:
        changed = False
        with self._operations:
            with self._lock:
                jobs = [(j.id, j.gid) for j in self._jobs.values()
                        if j.state in ACTIVE_STATES and j.id not in self._finishing and j.gid]
            if not jobs:
                return
            try:
                statuses = self._engine.statuses(tuple(gid for _, gid in jobs))
            except Exception:
                self._poll_failures += 1
                if self._poll_failures >= 3 and not self._engine.is_alive():
                    detail = self._engine.log_tail()
                    with self._lock:
                        for job_id, _ in jobs:
                            self._terminal(self._jobs[job_id], "interrupted",
                                           t("aria2c stopped unexpectedly: {detail}", detail=detail))
                        changed = True
            else:
                self._poll_failures = 0
                for (job_id, gid), status in zip(jobs, statuses):
                    changed = self._apply_status(job_id, gid, status) or changed
        if changed:
            self._notify()

    def _note(self, job_id: str, text: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.cancel_event.is_set():
                return
            job.notes += (text,)
            job.updated_at = time.time()
            self._bump()
        self._notify()

    def _remove_result(self, job_id: str, gid: str) -> None:
        try:
            self._engine.remove_result(gid)
        except Exception as error:
            self._note(job_id, t("Could not clear aria2c's download result: {error}", error=error))

    def _apply_status(self, job_id: str, gid: str, status: dict) -> bool:
        followed = status.get("followedBy", [])
        if followed:
            with self._lock:
                job = self._jobs[job_id]
                job.gid, job.state = followed[0], "metadata"
                self._metadata.discard(job_id)
                job.done_bytes = job.total_bytes = job.speed_bps = 0
                job.eta_s = None
                job.updated_at = time.time()
                if job.started_at is None:
                    job.started_at = job.updated_at
                self._bump()
            self._remove_result(job_id, gid)
            return True
        remote = status.get("status")
        # Metadata can finish just before followedBy becomes observable. Wait
        # for the handoff; metadata bytes are never payload progress or success.
        if remote == "complete" and job_id in self._metadata:
            with self._lock:
                job = self._jobs[job_id]
                if job.state != "metadata":
                    job.state = "metadata"
                    return self._bump()
            return False
        if remote == "error":
            detail = self._engine.log_tail()
            message = t("aria2c download failed: {error}", error=status.get("errorMessage") or status.get("errorCode", ""))
            with self._lock:
                job = self._jobs[job_id]
                if detail:
                    job.notes += (t("aria2c log: {detail}", detail=detail),)
                self._terminal(job, "failed", message)
            self._remove_result(job_id, gid)
            return True
        with self._lock:
            job = self._jobs[job_id]
            before = (job.done_bytes, job.total_bytes, job.speed_bps, job.peers, job.seeds, job.eta_s)
            job.done_bytes = int(status.get("completedLength", 0))
            job.total_bytes = int(status.get("totalLength", 0))
            job.speed_bps = int(status.get("downloadSpeed", 0))
            job.peers = int(status.get("connections", 0))
            job.seeds = int(status.get("numSeeders", 0))
            job.eta_s = max(0, job.total_bytes - job.done_bytes) // job.speed_bps if job.speed_bps else None
            state = {"waiting": "queued", "paused": "paused", "removed": "stopped"}.get(remote, "running")
            if remote == "active" and (job_id in self._metadata
                                       or status.get("bittorrent", {}).get("mode") == "metadata"
                                       or (job.magnet.startswith("magnet:") and not job.total_bytes)):
                state = "metadata"
                job.done_bytes = job.total_bytes = job.speed_bps = 0
                job.eta_s = None
            if remote == "complete":
                if job.started_at is None:
                    job.started_at = time.time()
                job.files = tuple(f["path"] for f in status.get("files", [])
                                  if f.get("selected") == "true" and f.get("path"))
                job.speed_bps, job.eta_s = 0, None
                self._finishing.add(job_id)
                changed = self._bump()
            elif state == "stopped":
                job.cancel_event.set()
                self._terminal(job, state)
                changed = True
            elif state != job.state:
                job.state = state
                if state in ("metadata", "running") and job.started_at is None:
                    job.started_at = time.time()
                changed = self._bump()
            else:
                after = (job.done_bytes, job.total_bytes, job.speed_bps, job.peers, job.seeds, job.eta_s)
                changed = self._bump(progress=True) if before != after else False
            job.updated_at = time.time()
        if remote == "complete":
            self._remove_result(job_id, gid)
            self._finish_queue.put(job_id)
        return changed

    def _finish_loop(self) -> None:
        while True:
            job_id = self._finish_queue.get()
            try:
                if job_id is None:
                    return
                self._finish(job_id)
            finally:
                self._finish_queue.task_done()

    def _finish(self, job_id: str) -> None:
        try:
            with self._lock:
                job = self._jobs[job_id]
                if job.cancel_event.is_set():
                    return
                paths = job.files
            if unpack.enabled():
                with self._lock:
                    if job.cancel_event.is_set():
                        return
                    job.state = "unpacking"
                    self._bump()
                self._notify()
                def status(text):
                    if job.cancel_event.is_set():
                        raise Cancelled()
                    self._note(job_id, text)
                    if job.cancel_event.is_set():
                        raise Cancelled()

                # unpack() reports most I/O errors as kept-packed reasons, so
                # catch Defender's initial lock while it still has a type.
                # Probe only the exact selected archive paths, never scan dir.
                for path in paths:
                    if not unpack.is_archive(path):
                        continue
                    for delay in (*_RETRY_DELAYS, None):
                        if job.cancel_event.is_set():
                            return
                        try:
                            with open(path, "rb"):
                                pass
                            break
                        except PermissionError:
                            if delay is None:
                                raise
                            if job.cancel_event.wait(delay):
                                return
                        except OSError:
                            break  # let unpack report missing/damaged archives
                report = None
                for delay in (*_RETRY_DELAYS, None):
                    if job.cancel_event.is_set():
                        return
                    try:
                        report = unpack.unpack_all(paths, expect_pages=job.expect_pages, status=status)
                        break
                    except PermissionError:
                        if delay is None:
                            raise
                        if job.cancel_event.wait(delay):
                            return
                for folder in report.unpacked:
                    self._note(job_id, t("Unpacked into {folder}", folder=folder))
                for path, reason in report.kept:
                    self._note(job_id, t("Kept {name} packed: {reason}",
                                         name=os.path.basename(path), reason=unpack.reason_label(reason)))
            with self._lock:
                if job.cancel_event.is_set():
                    return
                self._terminal(job, "done")
                # A direct download counts no download method, as in the foreground.
                record = job.backend != "direct" and job.group is None
                if job.group is not None and job.backend != "direct":
                    key = (job.group, job.method)
                    members = self._group_states[key].values()
                    record = (job.backend != "direct" and key not in self._counted_groups
                              and all(state == "done" for state in members))
                    if record:
                        self._counted_groups.add(key)
            if record:
                try:
                    stats.record_method_complete(job.method)
                except Exception as error:
                    self._note(job_id, t("Could not record download statistics: {error}", error=error))
        except Exception as error:
            # Payload is already downloaded. A finishing error keeps its files
            # and is visible rather than silently killing the finisher thread.
            with self._lock:
                if not job.cancel_event.is_set():
                    self._terminal(job, "failed", t("Could not finish the download: {error}", error=error))
        finally:
            with self._lock:
                self._finishing.discard(job_id)
            self._notify()

    def is_busy(self) -> bool:
        """True while a job is unfinished, or a stopped finisher or direct fetch has not returned yet."""
        with self._lock:
            return (bool(self._finishing) or bool(self._fetching)
                    or any(j.state in ACTIVE_STATES for j in self._jobs.values()))

    def shutdown(self, graceful: bool = True) -> None:
        """Stop jobs, save partials via aria2 shutdown, and join both workers.

        A currently executing unpack is allowed to return before joining; its
        cancellation prevents further finishing work or completion statistics.
        """
        with self._operations:
            with self._lock:
                if self._closed:
                    return
                self._closed = True
                self._stop.set()
                for job in self._jobs.values():
                    if job.state in ACTIVE_STATES:
                        job.cancel_event.set()
                        self._terminal(job, "stopped")
            try:
                self._engine.shutdown(graceful)
            finally:
                self._finish_queue.put(None)
                for _ in self._direct_workers:
                    self._direct_queue.put(None)
        # A direct worker checks Stop at every chunk; one stuck in a request
        # gives up at its timeout, and it is a daemon thread: wait only a while.
        deadline = time.monotonic() + 10
        for worker, done in zip(self._direct_workers, self._direct_done):
            if worker is threading.current_thread():
                continue
            while not done.is_set():  # the worker's own word, not is_alive(): see _direct_done
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                try:
                    done.wait(min(0.2, left))
                except KeyboardInterrupt:
                    continue  # a second Ctrl+C must not leave a file half-written
        for worker in (self._poller, self._finisher):
            if worker is not None and worker is not threading.current_thread():
                while worker.is_alive():
                    try:
                        worker.join(0.2)
                    except KeyboardInterrupt:
                        continue
        self._notify()


_manager: JobManager | None = None
_manager_lock = threading.Lock()


def manager() -> JobManager:
    """One lazy manager per app session; importing this module starts nothing."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = JobManager()
        return _manager


def current() -> JobManager | None:
    """The session's manager when a job has been enqueued, else None; starts nothing."""
    with _manager_lock:
        return _manager


def busy() -> bool:
    """Update/quit guard, including a finisher still returning after stop."""
    manager_now = current()
    return manager_now is not None and manager_now.is_busy()


def shutdown_all(graceful: bool = True) -> None:
    """Stop the session's jobs and workers, if a manager was ever started."""
    manager_now = current()
    if manager_now is not None:
        manager_now.shutdown(graceful)
