"""Play history for music: which song is on air, and whether it played to its end.

ffmpeg reads the music in real time (-re), so, like the on-screen song title, the
song playing is worked out from the wall clock and the stored durations. The stream
supervisor calls tick() about once a second and finish() when ffmpeg exits.

A recorder (see main.py) writes the rows; it is an object with
    started(playlist_id, song, mode, started_at) -> token
    finished(token, outcome, played_seconds, reason, ended_at)
Recorder errors are logged and never stop the stream."""
import logging
import time
from typing import Callable

from app.services.rotation import track_seconds

log = logging.getLogger("reztv.playtrack")

# A song stopped within this many seconds of its end still counts as played to the end.
NATURAL_SLACK_SECONDS = 2.0


class PlayTracker:
    def __init__(self, playlist_id: int, mode: str, songs: list[dict], recorder=None,
                 clock: Callable[[], float] = time.time):
        self.playlist_id, self.mode, self.songs = playlist_id, mode, songs
        self.recorder, self.clock = recorder, clock
        self.bounds = []          # (start offset, end offset) per song
        t = 0.0
        for s in songs:
            self.bounds.append((t, t + track_seconds(s)))
            t += track_seconds(s)
        self.t0: float | None = None
        self.idx = -1             # song currently open in the history
        self.token = None
        self.done = False

    # --- recorder calls, never raising ---
    def _started(self, i: int, at: float):
        self.idx, self.token = i, None
        if self.recorder:
            try:
                self.token = self.recorder.started(self.playlist_id, self.songs[i], self.mode, at)
            except Exception:
                log.exception("Could not record play start")

    def _finished(self, outcome: str, played: float, reason: str | None, at: float):
        if self.recorder and self.token is not None:
            try:
                self.recorder.finished(self.token, outcome, round(max(played, 0.0), 1), reason, at)
            except Exception:
                log.exception("Could not record play end")
        self.token = None

    # --- driven by the supervisor ---
    def start(self):
        self.t0 = self.clock()
        if self.songs:
            self._started(0, self.t0)

    def _index_at(self, elapsed: float) -> int:
        for i, (_, end) in enumerate(self.bounds):
            if elapsed < end:
                return i
        return len(self.bounds) - 1   # past the planned end: last song until ffmpeg exits

    def tick(self):
        if self.done or self.t0 is None or not self.songs:
            return
        target = self._index_at(self.clock() - self.t0)
        while self.idx < target:
            start, end = self.bounds[self.idx]
            self._finished("natural", end - start, None, self.t0 + end)
            self._started(self.idx + 1, self.t0 + end)

    def finish(self, completed: bool, reason: str | None = None):
        """ffmpeg is gone. completed=True means it exited normally at the end of the
        music (every planned song played out); otherwise the open song is cut unless
        it was within a couple of seconds of its end."""
        if self.done or self.t0 is None or not self.songs:
            self.done = True
            return
        now = self.clock()
        if completed:
            while self.idx < len(self.songs) - 1:
                start, end = self.bounds[self.idx]
                self._finished("natural", end - start, None, self.t0 + end)
                self._started(self.idx + 1, self.t0 + end)
            start, end = self.bounds[self.idx]
            self._finished("natural", end - start, None, now)
        else:
            self.tick()
            start, end = self.bounds[self.idx]
            played = now - self.t0 - start
            natural = played >= (end - start) - NATURAL_SLACK_SECONDS
            self._finished("natural" if natural else "cut", played,
                           None if natural else reason, now)
        self.done = True
