"""The cut-off songs fix, end to end with real ffmpeg: a song longer than the
filler block plays to its end (the block runs long), then the next block starts."""
import shutil
import subprocess
import time

import pytest

from app.services import hls
from app.services.convert import build_audio_command, measure_duration

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def _clip(path, seconds=2):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"testsrc=size=320x240:rate=30:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)


def _song(tmp_path, name, seconds):
    wav = tmp_path / f"{name}.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"sine=frequency=440:duration={seconds}", str(wav)], check=True)
    out = tmp_path / f"{name}.mka"
    subprocess.run(build_audio_command(str(wav), str(out)), check=True, capture_output=True)
    return out


class Capture:
    def __init__(self):
        self.rows = []

    def started(self, pid, song, mode, started_at):
        self.rows.append({"id": song.get("id"), "started_at": started_at, "outcome": None})
        return len(self.rows) - 1

    def finished(self, token, outcome, played, reason, ended_at):
        self.rows[token].update(outcome=outcome, played=played, reason=reason, ended_at=ended_at)


def test_song_longer_than_filler_block_plays_to_its_end(tmp_path, monkeypatch):
    monkeypatch.setattr(hls, "HLS_PATH", str(tmp_path / "hls"))
    monkeypatch.setattr(hls, "LOG_PATH", str(tmp_path / "logs"))
    clip = tmp_path / "filler.mp4"
    _clip(clip)
    song = _song(tmp_path, "song", 5)
    length = measure_duration(str(song))
    assert 4.9 < length < 5.2
    src = {"mode": "mixed", "video": [], "filler": [str(clip)], "audio": [str(song)],
           "audio_meta": [{"id": 1, "title": "Song", "duration": length}],
           "filler_meta": [{"id": 2, "title": "Filler", "duration": 2.0}],
           "filler_seconds": 2,          # block "length" is shorter than the song
           "overlay": False, "rotation": {"gap_tracks": 0, "gap_minutes": 0}}
    rec = Capture()
    ch = hls._Channel(4242, lambda: src, rec)
    ch.start()
    try:
        deadline = time.time() + 40
        while time.time() < deadline and not (rec.rows and rec.rows[0]["outcome"]):
            time.sleep(0.2)
    finally:
        ch.stop()
    first = rec.rows[0]
    assert first["outcome"] == "natural" and first["reason"] is None
    # The block lasted the whole song (old code cut it at the 2 s block length).
    assert first["ended_at"] - first["started_at"] >= length - 0.5
    assert abs(first["played"] - length) < 0.2
    log = (tmp_path / "logs" / "channel_4242.log").read_text()
    assert "Slot finished; next: filler" in log      # exit 0, straight to the next block
    # The first block's HLS output holds the whole song (one 6 s segment at most).
    seg = tmp_path / "hls" / "playlist_4242" / "segment_000.ts"
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(seg)], capture_output=True, text=True).stdout
    assert float(out) >= length - 0.5


def test_separate_audio_session_ends_on_song_boundary(tmp_path, monkeypatch):
    """A separate-audio session is whole songs; when it ends, the next starts at once
    and every song in the first session counts as played to its end."""
    monkeypatch.setattr(hls, "HLS_PATH", str(tmp_path / "hls"))
    monkeypatch.setattr(hls, "LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setattr(hls, "AUDIO_SESSION_MINUTES", 0.05)   # 3 s target
    clip = tmp_path / "v.mp4"
    _clip(clip, 3)
    a, b = _song(tmp_path, "a", 2), _song(tmp_path, "b", 2)
    src = {"mode": "separate_audio", "video": [str(clip)], "audio": [str(a), str(b)],
           "video_meta": [{"id": 9, "title": "V", "duration": 3.0}],
           "audio_meta": [{"id": 1, "title": "A", "duration": measure_duration(str(a))},
                          {"id": 2, "title": "B", "duration": measure_duration(str(b))}],
           "overlay": False, "rotation": {"gap_tracks": 0, "gap_minutes": 0}}
    rec = Capture()
    ch = hls._Channel(4243, lambda: src, rec)
    ch.start()
    try:
        deadline = time.time() + 40
        while time.time() < deadline and not (len(rec.rows) >= 3):
            time.sleep(0.2)
    finally:
        ch.stop()
    assert [r["id"] for r in rec.rows[:2]] == [1, 2]
    assert [r["outcome"] for r in rec.rows[:2]] == ["natural", "natural"]
    log = (tmp_path / "logs" / "channel_4243.log").read_text()
    assert "Music session finished; starting the next one" in log
