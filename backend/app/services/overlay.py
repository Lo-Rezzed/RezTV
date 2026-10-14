"""On-screen info for separate-audio playback (separate_audio channels and mixed
filler blocks): the media ID of the clip on screen (bottom left) and the title of
the song playing (bottom right).

ffmpeg draws two text files with drawtext (reload=1). A small ticker thread works
out which clip and which song are playing from the wall clock (inputs are read in
real time with -re) and the stored durations, and rewrites the files atomically."""
import os
import threading
import time
from pathlib import Path

OVERLAY_FONT = os.getenv("OVERLAY_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
OVERLAY_OPACITY = float(os.getenv("OVERLAY_OPACITY", "0.6"))
DEFAULT_ITEM_SECONDS = 10.0  # used when a duration is unknown


def _esc(value: str) -> str:
    """Escape a value for use inside an ffmpeg filter option."""
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def drawtext_filters(id_file: Path, song_file: Path) -> str:
    font = f":fontfile={_esc(OVERLAY_FONT)}" if OVERLAY_FONT and os.path.exists(OVERLAY_FONT) else ""
    common = (f"reload=1:expansion=none{font}:fontsize=h/40:fontcolor=white@{OVERLAY_OPACITY}"
              f":shadowcolor=black@{OVERLAY_OPACITY}:shadowx=1:shadowy=1:y=h-th-h*0.035")
    return (f"drawtext=textfile={_esc(str(id_file))}:{common}:x=w*0.02,"
            f"drawtext=textfile={_esc(str(song_file))}:{common}:x=w-tw-w*0.02")


def item_at(durations: list[float], elapsed: float) -> int:
    """Index of the item playing `elapsed` seconds into an endlessly looped list."""
    if not durations:
        return 0
    d = [x if x and x > 0 else DEFAULT_ITEM_SECONDS for x in durations]
    t = elapsed % sum(d)
    for i, x in enumerate(d):
        if t < x:
            return i
        t -= x
    return len(d) - 1


def _clean(text: str, limit: int = 80) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"


def write_atomic(path: Path, text: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def label_for_clip(meta: dict) -> str:
    return f"ID {meta['id']}" if meta.get("id") is not None else ""


def label_for_song(meta: dict) -> str:
    title = meta.get("title") or ""
    for ext in (".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".mka"):
        if title.lower().endswith(ext):
            title = title[: -len(ext)]
    return "\u266a " + _clean(title) if title else ""


class OverlayTicker:
    def __init__(self, id_file: Path, song_file: Path, clips: list[dict], songs: list[dict]):
        self.id_file, self.song_file = id_file, song_file
        self.clips, self.songs = clips, songs
        self._stop = threading.Event()
        self._last = (None, None)
        self.render(0.0)  # files must exist before ffmpeg opens them

    def render(self, elapsed: float):
        clip = self.clips[item_at([c.get("duration") for c in self.clips], elapsed)] if self.clips else {}
        song = self.songs[item_at([s.get("duration") for s in self.songs], elapsed)] if self.songs else {}
        texts = (label_for_clip(clip), label_for_song(song))
        if texts != self._last:
            write_atomic(self.id_file, texts[0])
            write_atomic(self.song_file, texts[1])
            self._last = texts

    def start(self):
        started = time.monotonic()

        def run():
            while not self._stop.wait(0.5):
                try:
                    self.render(time.monotonic() - started)
                except OSError:
                    pass
        threading.Thread(target=run, daemon=True, name="overlay").start()

    def stop(self):
        self._stop.set()
