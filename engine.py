import re
import requests
import asyncio
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager


class LyricsEngine:
    def __init__(self):
        self.current_track_id = None
        self.lyrics_data = []
        self.lyrics_keys = []
        self.lyrics_unavailable = False
        self._session = None  # Cached session for fast position reads

    def _get_session(self):
        """Fetch and cache the current media session."""
        loop = asyncio.new_event_loop()
        try:
            manager = loop.run_until_complete(
                GlobalSystemMediaTransportControlsSessionManager.request_async()
            )
            if manager:
                self._session = manager.get_current_session()
            else:
                self._session = None
        except Exception:
            self._session = None
        finally:
            loop.close()

    def get_position_ms(self):
        """Fast synchronous read of the current playback position from cached session."""
        if not self._session:
            return 0
        try:
            timeline = self._session.get_timeline_properties()
            return int(timeline.position.total_seconds() * 1000)
        except Exception:
            return 0

    def get_is_playing(self):
        """Fast synchronous read of playback status from cached session."""
        if not self._session:
            return False
        try:
            # playback_status == 4 means Playing
            return self._session.get_playback_info().playback_status == 4
        except Exception:
            return False

    def update(self):
        """
        Called every ~3s. Refreshes the session, checks for track changes,
        and fetches new lyrics if the track changed.
        """
        self._get_session()
        if not self._session:
            self.current_track_id = None
            return None

        try:
            loop = asyncio.new_event_loop()
            info = loop.run_until_complete(
                self._session.try_get_media_properties_async()
            )
            loop.close()
        except Exception:
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
            duration_ms = 1

        # Track changed — fetch new lyrics
        if unique_id != self.current_track_id:
            self.current_track_id = unique_id
            self.fetch_lyrics(
                track_name=title,
                artist_name=artist,
                album_name=info.album_title or "",
                duration_ms=duration_ms,
            )

        return {
            "id": unique_id,
            "name": title,
            "artist": artist,
        }

    def fetch_lyrics(self, track_name, artist_name, album_name, duration_ms):
        url = "https://lrclib.net/api/get"
        duration_s = round(duration_ms / 1000)
        params = {"track_name": track_name, "artist_name": artist_name, "duration": duration_s}
        if album_name:
            params["album_name"] = album_name

        try:
            headers = {"User-Agent": "SpotLrc/1.0 (https://github.com/gamal/SpotLrc)"}
            response = requests.get(url, params=params, headers=headers)

            if response.status_code == 200:
                data = response.json()
                synced = data.get("syncedLyrics")
                if synced:
                    self.parse_lrc(synced)
                    self.lyrics_unavailable = False
                else:
                    self.lyrics_data = []
                    self.lyrics_unavailable = True
            else:
                self.lyrics_data = []
                self.lyrics_unavailable = True
        except Exception as e:
            print(f"Error fetching lyrics from LrcLib: {e}")
            self.lyrics_data = []
            self.lyrics_unavailable = True

    def parse_lrc(self, lrc_string):
        self.lyrics_data = []
        pattern = re.compile(r"\[(\d+):(\d+\.\d+)\](.*)")

        for line in lrc_string.splitlines():
            match = pattern.match(line)
            if match:
                minutes = int(match.group(1))
                seconds = float(match.group(2))
                text = match.group(3).strip()
                total_ms = int((minutes * 60 + seconds) * 1000)
                self.lyrics_data.append((total_ms, text))

        self.lyrics_data.sort(key=lambda x: x[0])
        self.lyrics_keys = [x[0] for x in self.lyrics_data]

    def get_current_lyric(self, current_ms):
        import bisect

        if self.lyrics_unavailable:
            return "Lyrics not available"

        if not self.lyrics_data:
            return ""

        idx = bisect.bisect_right(self.lyrics_keys, current_ms)

        if idx == 0:
            return ""

        text = self.lyrics_data[idx - 1][1]
        return "\u266b" if text == "" else text


if __name__ == "__main__":
    engine = LyricsEngine()
    print("Polling Windows Media...")
    playback = engine.update()
    if playback:
        pos = engine.get_position_ms()
        print(f"Currently playing: '{playback['name']}' by {playback['artist']}")
        print(f"Current Time: {pos}ms")
        print(f"Lyric Line: {engine.get_current_lyric(pos)}")
    else:
        print("Nothing detected on Windows Media.")
