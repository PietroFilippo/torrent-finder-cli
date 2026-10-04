"""TorrentSession: post-torrent-pick state owner.

Constructed once per torrent the user picks, lives for the duration of the
download-method menu loop. Stream adapters consume it directly; download
adapters take ``session.magnet`` + ``session.download_indexes`` projections
and stay session-unaware (see CONTEXT.md).
"""

from torrent_finder.torrent_meta import (
    TorrentFile,
    TorrentMetadata,
    fetch_file_list,
    is_multi_episode,
    sort_episodes,
    video_files,
)


class TorrentSession:
    def __init__(self, result_dict: dict, magnet: str) -> None:
        self.result = result_dict
        self.magnet = magnet
        self.name: str = result_dict.get("name", "Unknown")
        self.selected_files: list[int] | None = None
        self.sub_choice: dict | None = None
        self._files_meta: TorrentMetadata | None = None
        # "unknown" until a fetch completes; "unavailable" after one found no
        # metadata (timeout, no peers), which a later explicit fetch retries.
        self.files_meta_status = "unknown"
        # In-torrent subtitle files fetched so far (file index → local copy),
        # reused by later streams of this torrent.
        self._sub_files: dict[int, str] = {}

    # ---- Setters ----

    def set_selected_files(self, indexes: list[int] | None) -> None:
        self.selected_files = indexes

    def set_sub_choice(self, choice: dict | None) -> None:
        self.sub_choice = choice

    # ---- Metadata (fetched explicitly, kept once found) ----

    @property
    def files_meta(self) -> TorrentMetadata | None:
        """The file list once fetched. Never fetches by itself: callers use the
        cancellable ``fetch_files_meta`` first (a silent wait couldn't be
        cancelled and would start a stream on a default file)."""
        return self._files_meta

    def fetch_files_meta(self, cancel_event=None) -> TorrentMetadata | None:
        """Fetch the file list unless it is already known.

        A successful result is kept and reused for the session. A failed
        attempt (timeout, no metadata peers) sets ``files_meta_status`` to
        "unavailable" but is not final: the next call tries again. Cancelling
        changes nothing.
        """
        if self._files_meta is not None:
            return self._files_meta
        result = fetch_file_list(self.magnet, cancel_event=cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            return None  # aborted — nothing learned
        self.files_meta_status = "ok" if result is not None else "unavailable"
        if result is not None:
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

    # ---- Subtitles for the episodes being streamed ----

    @property
    def sub_paths(self) -> dict[int, list[str]]:
        """``{video_index: [subtitle paths]}`` for the episodes this stream plays.

        Auto-detected in-torrent subtitles are fetched only for those episodes,
        all before playback starts (so n/b never waits for subtitles), and kept
        for later streams, which fetch only what they don't have yet.
        """
        from torrent_finder.downloader import _resolve_subs_for_session
        return _resolve_subs_for_session(
            self.magnet, self.files_meta, self.file_list, self.sub_choice,
            targets=self.stream_indexes or None, fetched=self._sub_files,
        )
