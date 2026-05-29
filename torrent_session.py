"""TorrentSession: post-torrent-pick state owner.

Constructed once per torrent the user picks, lives for the duration of the
download-method menu loop. Stream adapters consume it directly; download
adapters take ``session.magnet`` + ``session.download_indexes`` projections
and stay session-unaware (see CONTEXT.md).
"""

from torrent_meta import (
    TorrentFile,
    TorrentMetadata,
    fetch_file_list,
    is_multi_episode,
    sort_episodes,
    video_files,
)


_UNSET = object()


class TorrentSession:
    def __init__(self, result_dict: dict, magnet: str) -> None:
        self.result = result_dict
        self.magnet = magnet
        self.name: str = result_dict.get("name", "Unknown")
        self.selected_files: list[int] | None = None
        self.sub_choice: dict | None = None
        self._files_meta = _UNSET
        self._sub_paths: dict[int, list[str]] | None = None

    # ---- Setters ----

    def set_selected_files(self, indexes: list[int] | None) -> None:
        self.selected_files = indexes

    def set_sub_choice(self, choice: dict | None) -> None:
        self.sub_choice = choice
        self._sub_paths = None

    # ---- Lazy metadata (cached) ----

    @property
    def files_meta(self) -> TorrentMetadata | None:
        if self._files_meta is _UNSET:
            self._files_meta = fetch_file_list(self.magnet)
        return self._files_meta

    def fetch_files_meta(self, cancel_event=None) -> TorrentMetadata | None:
        """Cancellable variant of the ``files_meta`` property.

        Caches a real result (success or genuine failure/timeout) so repeat
        accesses are instant, but does NOT cache when the user cancelled —
        leaving the cache unset so a later retry re-fetches.
        """
        if self._files_meta is not _UNSET:
            return self._files_meta
        result = fetch_file_list(self.magnet, cancel_event=cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            return None  # aborted — keep cache unset for retry
        self._files_meta = result
        return result

    @property
    def file_list(self) -> list[TorrentFile]:
        m = self.files_meta
        return m.files if m else []

    @property
    def torrent_name(self) -> str | None:
        m = self.files_meta
        return m.name if m else None

    # ---- Derived (recomputed each access) ----

    @property
    def targets(self) -> list[int]:
        fl = self.file_list
        if not fl or not is_multi_episode(fl):
            return []
        return [f.index for f in sort_episodes(fl)]

    @property
    def stream_indexes(self) -> list[int]:
        """Resolved index list for streaming with video-only filter applied.

        Precedence:
          1. selected_files filtered to video-only. When metadata is unavailable
             the filter is skipped — trust the user's selection.
          2. multi-episode targets (already video-only).
          3. ``[largest_video_index]`` for single-video torrents.
          4. ``[]`` when no metadata at all — adapter falls through to a
             backend default by passing ``[None]``.
        """
        fl = self.file_list
        sel = self.selected_files
        if sel:
            if not fl:
                return list(sel)
            video_idxs = {f.index for f in video_files(fl)}
            return [i for i in sel if i in video_idxs]
        t = self.targets
        if t:
            return t
        if not fl:
            return []
        videos = video_files(fl)
        if not videos:
            return []
        return [max(videos, key=lambda f: f.size_bytes).index]

    @property
    def download_indexes(self) -> list[int] | None:
        return list(self.selected_files) if self.selected_files else None

    # ---- Lazy subs (cached; invalidated by set_sub_choice) ----

    @property
    def sub_paths(self) -> dict[int, list[str]]:
        if self._sub_paths is None:
            from downloader import _resolve_subs_for_session
            self._sub_paths = _resolve_subs_for_session(
                self.magnet, self.files_meta, self.file_list, self.sub_choice
            )
        return self._sub_paths
