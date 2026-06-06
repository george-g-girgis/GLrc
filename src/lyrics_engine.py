"""
GLrc — Lyrics engine.

Reads the currently playing track from Windows Media Transport Controls,
fetches time-synced lyrics from LrcLib, and provides O(log N) lyric lookups.

Lyrics are fetched in a background QThread so the UI never blocks on HTTP.
"""

import bisect
import logging
import re
import asyncio
import os
import json
import hashlib

import requests
from PyQt6.QtCore import QThread, pyqtSignal
from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager,
)
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

# Reusable session to skip TCP/TLS handshakes on subsequent requests
_HTTP_SESSION = requests.Session()
_retries = Retry(total=2, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
_HTTP_SESSION.mount('https://', HTTPAdapter(max_retries=_retries))


# ── Background worker for non-blocking HTTP ──────────────────────────────

class LyricsFetchWorker(QThread):
    """Fetches lyrics from LrcLib on a background thread."""

    finished = pyqtSignal(list, bool)  # (lyrics_data, unavailable)

    def __init__(self, track_name: str, artist_name: str,
                 album_name: str, duration_ms: int, cache_dir: str, parent=None):
        super().__init__(parent)
        self.raw_track_name = track_name
        self.track_name = self._clean_title(track_name)
        self.artist_name = artist_name
        self.album_name = album_name
        self.duration_ms = duration_ms
        self.cache_dir = cache_dir

    # ── helpers ──

    @staticmethod
    def _clean_title(title: str) -> str:
        """Strip (Remastered...), [Live...], trailing suffixes, and YouTube pipes."""
        title = title.split(' | ')[0]
        title = title.split(' - ')[0]
        title = re.sub(r'\(.*?\)', '', title)
        title = re.sub(r'\[.*?\]', '', title)
        return title.strip()

    @staticmethod
    def _parse_lrc(lrc_string: str) -> list[tuple[int, str]]:
        """Parse an LRC string into sorted (ms, text) tuples."""
        data = []
        pattern = re.compile(r"\[(\d+):(\d+\.\d+)\](.*)")
        for line in lrc_string.splitlines():
            m = pattern.match(line)
            if m:
                minutes = int(m.group(1))
                seconds = float(m.group(2))
                text = m.group(3).strip()
                total_ms = int((minutes * 60 + seconds) * 1000)
                data.append((total_ms, text))
        data.sort(key=lambda x: x[0])
        return data

    @staticmethod
    def _headers() -> dict:
        return {"User-Agent": "GLrc/3.0 (https://github.com/gamal/GLrc)"}

    # ── LrcLib: exact match ──

    def _try_exact(self) -> list[tuple[int, str]] | None:
        """Try /api/get (exact metadata match) using the RAW title."""
        params: dict = {
            "track_name": self.raw_track_name,
            "artist_name": self.artist_name,
            "duration": round(self.duration_ms / 1000),
        }
        if self.album_name:
            params["album_name"] = self.album_name

        resp = _HTTP_SESSION.get(
            "https://lrclib.net/api/get",
            params=params,
            headers=self._headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            synced = resp.json().get("syncedLyrics")
            if synced:
                return self._parse_lrc(synced)
        return None

    # ── LrcLib: search fallback ──

    def _try_search(self, use_raw: bool = True) -> list[tuple[int, str]] | None:
        """Fallback to /api/search?q= and pick the best synced result."""
        search_title = self.raw_track_name if use_raw else self.track_name
        query = f"{search_title} {self.artist_name}"
        resp = _HTTP_SESSION.get(
            "https://lrclib.net/api/search",
            params={"q": query},
            headers=self._headers(),
            timeout=10,
        )
        if resp.status_code != 200:
            return None

        results = resp.json()
        if not isinstance(results, list):
            return None

        # Filter to entries that have synced lyrics
        synced_results = [r for r in results if r.get("syncedLyrics")]
        if not synced_results:
            return None

        target_dur = self.duration_ms / 1000
        if target_dur <= 1:
            return self._parse_lrc(synced_results[0]["syncedLyrics"])

        best = min(
            synced_results,
            key=lambda r: abs((r.get("duration") or 0) - target_dur),
        )
        return self._parse_lrc(best["syncedLyrics"])

    def _get_cache_path(self) -> str:
        key = f"{self.raw_track_name}-{self.artist_name}".encode("utf-8")
        h = hashlib.md5(key).hexdigest()
        return os.path.join(self.cache_dir, f"{h}.json")

    def run(self):
        try:
            cache_path = self._get_cache_path()
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data = [(int(ms), text) for ms, text in data]
                    self.finished.emit(data, False)
                    return
                except Exception:
                    pass  # Fall through to network

            data = self._try_exact()
            if data is None:
                log.info(
                    "Exact LrcLib match failed for '%s' — trying raw search.",
                    self.raw_track_name,
                )
                data = self._try_search(use_raw=True)
                
            if data is None:
                log.info(
                    "Raw search failed for '%s' — trying cleaned search ('%s').",
                    self.raw_track_name, self.track_name
                )
                data = self._try_search(use_raw=False)

            if data:
                try:
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(data, f)
                except Exception:
                    pass
                self.finished.emit(data, False)
            else:
                log.info("No synced lyrics found for '%s'.", self.track_name)
                self.finished.emit([], True)

        except requests.RequestException as e:
            log.warning("Network issue fetching lyrics for '%s': %s", self.track_name, e)
            self.finished.emit([], True)
        except Exception:
            log.exception("Unexpected error fetching lyrics for '%s'.", self.track_name)
            self.finished.emit([], True)


# ── Main engine ──────────────────────────────────────────────────────────

class LyricsEngine:
    """
    Manages the media session and lyrics state.

    - `update()` is called periodically (~3s) to detect track changes.
    - `get_position_ms()` / `get_is_playing()` are called every ~100ms.
    - Lyrics are fetched asynchronously via `LyricsFetchWorker`.
    """

    def __init__(self):
        self.current_track_id: str | None = None
        self.lyrics_data: list[tuple[int, str]] = []
        self.lyrics_keys: list[int] = []
        self.lyrics_unavailable: bool = False
        self.target_app_id: str | None = None
        self._session = None
        self._fetch_worker: LyricsFetchWorker | None = None

        appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
        self.cache_dir = os.path.join(appdata, "GLrc", "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.sync_offset_ms = 0

        # Persistent event loop for WinRT async calls
        self._loop = asyncio.new_event_loop()

    # ── Session management (single event loop, reused) ───────────────

    def _get_session(self):
        """Refresh the cached media session using the persistent event loop."""
        try:
            manager = self._loop.run_until_complete(
                GlobalSystemMediaTransportControlsSessionManager.request_async()
            )
            if not manager:
                self._session = None
                return

            if self.target_app_id:
                sessions = manager.get_sessions()
                # Find the session with the matching app id
                for s in sessions:
                    if s.source_app_user_model_id == self.target_app_id:
                        self._session = s
                        return
                
                # If target app is not playing anything, keep session as None
                self._session = None
            else:
                self._session = manager.get_current_session()
        except Exception:
            log.exception("Failed to get media session.")
            self._session = None

    def get_available_sessions(self) -> list[tuple[str, str]]:
        """Return a list of (display_name, app_id) for all active media sessions."""
        try:
            manager = self._loop.run_until_complete(
                GlobalSystemMediaTransportControlsSessionManager.request_async()
            )
            if not manager:
                return []
            
            sessions = manager.get_sessions()
            result = []
            for s in sessions:
                app_id = s.source_app_user_model_id
                
                # Format to a readable name
                name = app_id
                if "Spotify" in app_id:
                    name = "Spotify"
                elif "Chrome" in app_id:
                    name = "Google Chrome"
                elif "msedge" in app_id.lower() or "edge" in app_id.lower():
                    name = "Microsoft Edge"
                elif "AppleMusic" in app_id:
                    name = "Apple Music"
                elif "Firefox" in app_id:
                    name = "Firefox"
                elif "!" in app_id:
                    name = app_id.split("!")[-1]
                
                result.append((name, app_id))
            return result
        except Exception:
            log.exception("Failed to get available sessions.")
            return []

    # ── Fast synchronous reads (called every ~100ms) ─────────────────

    def get_position_ms(self) -> int:
        """Read playback position from the cached session."""
        if not self._session:
            return 0
        try:
            timeline = self._session.get_timeline_properties()
            return int(timeline.position.total_seconds() * 1000)
        except Exception:
            log.debug("Failed to read position.", exc_info=True)
            return 0

    def get_is_playing(self) -> bool:
        """Read playback status from the cached session."""
        if not self._session:
            return False
        try:
            return self._session.get_playback_info().playback_status == 4
        except Exception:
            log.debug("Failed to read playback status.", exc_info=True)
            return False

    # ── Periodic update (~3s) ────────────────────────────────────────

    def update(self) -> dict | None:
        """
        Refresh session, detect track changes, kick off lyrics fetch.
        Returns track info dict or None.
        """
        self._get_session()
        if not self._session:
            self.current_track_id = None
            return None

        try:
            info = self._loop.run_until_complete(
                self._session.try_get_media_properties_async()
            )
        except Exception:
            log.exception("Failed to get media properties.")
            return None

        title = info.title
        artist = info.artist
        if not title or not artist:
            return None

        unique_id = f"{title}-{artist}"

        try:
            timeline = self._session.get_timeline_properties()
            duration_ms = int(timeline.end_time.total_seconds() * 1000)
        except Exception:
            log.warning("Failed to read duration — defaulting to 1ms.")
            duration_ms = 1

        if unique_id != self.current_track_id:
            self.current_track_id = unique_id
            self.lyrics_data = []
            self.lyrics_keys = []
            self.lyrics_unavailable = False
            self.sync_offset_ms = 0  # Reset offset on track change
            self._start_lyrics_fetch(title, artist, info.album_title or "", duration_ms)

        return {"id": unique_id, "name": title, "artist": artist}

    # ── Async lyrics fetch ───────────────────────────────────────────

    def _start_lyrics_fetch(self, track: str, artist: str,
                            album: str, duration_ms: int):
        """Kick off a background thread to fetch lyrics."""
        # Cancel any in-flight fetch
        if self._fetch_worker and self._fetch_worker.isRunning():
            self._fetch_worker.quit()
            self._fetch_worker.wait(500)

        self._fetch_worker = LyricsFetchWorker(track, artist, album, duration_ms, self.cache_dir)
        self._fetch_worker.finished.connect(self._on_lyrics_fetched)
        self._fetch_worker.start()

    def _on_lyrics_fetched(self, data: list, unavailable: bool):
        """Slot called when the background fetch completes."""
        self.lyrics_data = data
        self.lyrics_keys = [t for t, _ in data]
        self.lyrics_unavailable = unavailable

    # ── Lyric lookup (O(log N)) ──────────────────────────────────────

    def get_current_lyric(self, current_ms: int) -> str:
        current_ms += self.sync_offset_ms
        if self.lyrics_unavailable:
            return "Lyrics not available"
        if not self.lyrics_data:
            return ""
        idx = bisect.bisect_right(self.lyrics_keys, current_ms)
        if idx == 0:
            return ""
        text = self.lyrics_data[idx - 1][1]
        return "\u266b" if text == "" else text

    def get_surrounding_lyrics(self, current_ms: int) -> tuple[str, str, str]:
        """Return (previous_line, current_line, next_line) for multi-line mode."""
        current_ms += self.sync_offset_ms
        if self.lyrics_unavailable:
            return ("", "Lyrics not available", "")
        if not self.lyrics_data:
            return ("", "", "")

        idx = bisect.bisect_right(self.lyrics_keys, current_ms)

        if idx == 0:
            # Before first lyric
            nxt = self.lyrics_data[0][1] if self.lyrics_data else ""
            return ("", "", nxt if nxt else "\u266b")

        current_idx = idx - 1
        cur_text = self.lyrics_data[current_idx][1]
        cur = cur_text if cur_text else "\u266b"

        # Previous line
        if current_idx > 0:
            prev_text = self.lyrics_data[current_idx - 1][1]
            prev = prev_text if prev_text else "\u266b"
        else:
            prev = ""

        # Next line
        if current_idx < len(self.lyrics_data) - 1:
            nxt_text = self.lyrics_data[current_idx + 1][1]
            nxt = nxt_text if nxt_text else "\u266b"
        else:
            nxt = ""

        return (prev, cur, nxt)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    engine = LyricsEngine()
    print("Polling Windows Media...")
    playback = engine.update()
    if playback:
        pos = engine.get_position_ms()
        print(f"Currently playing: '{playback['name']}' by {playback['artist']}")
        print(f"Current Time: {pos}ms")
        print(f"Lyric Line: {engine.get_current_lyric(pos)}")
        print(f"Surrounding: {engine.get_surrounding_lyrics(pos)}")
    else:
        print("Nothing detected on Windows Media.")
