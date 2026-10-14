"""ffmpeg stream management with supervision, auto-restart and per-channel logs."""
import logging
import os
import random
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

log = logging.getLogger("reztv.hls")

HLS_PATH = os.getenv("HLS_PATH", "/app/hls")
MEDIA_PATH = os.getenv("MEDIA_PATH", "/app/media")
LOG_PATH = os.getenv("LOG_PATH", "/app/logs")
LOG_MAX_BYTES = int(os.getenv("STREAM_LOG_MAX_KB", "1024")) * 1024
LOG_BACKUPS = 2
BACKOFF_START = float(os.getenv("STREAM_BACKOFF_START", "2"))
BACKOFF_MAX = float(os.getenv("STREAM_BACKOFF_MAX", "300"))
STABLE_SECONDS = float(os.getenv("STREAM_STABLE_SECONDS", "60"))
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
# Separate-audio channels: even out music volume live as well (music is already
# normalized once on upload, so this is off by default; it costs a little CPU).
STREAM_AUDIO_LOUDNORM = os.getenv("STREAM_AUDIO_LOUDNORM", "false").strip().lower() in {
    "1", "true", "yes", "on"}
STREAM_LOUDNORM_TARGET = float(os.getenv("STATION_LOUDNORM_TARGET", "-16"))

# playlist_id -> _Channel
running_processes: dict[int, "_Channel"] = {}
_lock = threading.Lock()


def log_file(playlist_id: int) -> Path:
    return Path(LOG_PATH) / f"channel_{playlist_id}.log"


class _RotatingWriter:
    """Size-capped log file: channel_N.log, rotated to .1, .2."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._f = open(path, "a", encoding="utf-8", errors="replace")

    def write(self, line: str):
        with self._lock:
            self._f.write(line if line.endswith("\n") else line + "\n")
            self._f.flush()
            if self._f.tell() >= LOG_MAX_BYTES:
                self._rotate()

    def _rotate(self):
        self._f.close()
        for i in range(LOG_BACKUPS, 0, -1):
            src = self.path if i == 1 else self.path.with_suffix(f".log.{i-1}")
            dst = self.path.with_suffix(f".log.{i}")
            if src.exists():
                os.replace(src, dst)
        self._f = open(self.path, "a", encoding="utf-8", errors="replace")

    def close(self):
        with self._lock:
            self._f.close()


_VIDEO_OUT = [
    "-vf", "fps=30,format=yuv420p",
    "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
    "-profile:v", "main", "-crf", "22", "-g", "60", "-keyint_min", "60",
    "-sc_threshold", "0", "-force_key_frames", "expr:gte(t,n_forced*2)",
    "-vsync", "cfr",
]
_AUDIO_OUT = ["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]


def _hls_out(stream_dir: Path, output_m3u8: Path) -> list[str]:
    # append_list + discont_start: when a mixed channel switches between a program
    # and a filler block, the next ffmpeg continues the same playlist and segment
    # numbering and marks the join, so viewers keep watching across the switch.
    return [
        "-f", "hls", "-hls_time", "6", "-hls_list_size", "10",
        "-hls_flags", "delete_segments+append_list+omit_endlist+independent_segments+discont_start",
        "-hls_segment_filename", str(stream_dir / "segment_%03d.ts"),
        str(output_m3u8),
    ]


def _build_cmd(concat_file: Path, stream_dir: Path, output_m3u8: Path,
               loop: bool = True) -> list[str]:
    """Standard channel: each video plays with its own sound.
    loop=False plays the list once and exits (a program slot on a mixed channel)."""
    return [
        FFMPEG_BIN, "-hide_banner", "-loglevel", "warning",
        "-re", "-f", "concat", "-safe", "0", "-stream_loop", "-1" if loop else "0",
        "-i", str(concat_file),
        *_VIDEO_OUT,
        "-af", "aresample=44100",
        *_AUDIO_OUT,
        *_hls_out(stream_dir, output_m3u8),
    ]


def _build_separate_audio_cmd(video_concat: Path, audio_concat: Path,
                              stream_dir: Path, output_m3u8: Path,
                              duration: float | None = None) -> list[str]:
    """Separate-audio channel: two inputs, each its own endless loop, read in real
    time. Picture comes from the video list (its sound is dropped), sound from the
    audio list. The two lists switch items independently, so a song keeps playing
    across video changes and vice versa."""
    # Plain resample, no async= padding: the concat input already gives continuous
    # timestamps, and async=1 was measured to insert ~0.1 s dropouts on loop.
    af = "aresample=44100"
    if STREAM_AUDIO_LOUDNORM:
        af = f"loudnorm=I={STREAM_LOUDNORM_TARGET}:TP=-1.5:LRA=11,{af}"
    return [
        FFMPEG_BIN, "-hide_banner", "-loglevel", "warning",
        "-re", "-f", "concat", "-safe", "0", "-stream_loop", "-1",
        "-i", str(video_concat),
        "-re", "-f", "concat", "-safe", "0", "-stream_loop", "-1",
        "-i", str(audio_concat),
        "-map", "0:v:0", "-map", "1:a:0",
        *_VIDEO_OUT,
        "-af", af,
        *_AUDIO_OUT,
        *(["-t", f"{duration:.0f}"] if duration else []),
        *_hls_out(stream_dir, output_m3u8),
    ]


DEFAULT_FILLER_SECONDS = 30 * 60


def _normalize_source(src) -> dict:
    """get_files may return a plain list (standard channel) or
    {"mode": ..., "video": [...], "audio": [...]}."""
    if isinstance(src, dict):
        return {"mode": src.get("mode") or "standard",
                "video": list(src.get("video") or []),
                "audio": list(src.get("audio") or []),
                "filler": list(src.get("filler") or []),
                "filler_seconds": float(src.get("filler_seconds") or DEFAULT_FILLER_SECONDS)}
    return {"mode": "standard", "video": list(src or []), "audio": [], "filler": [],
            "filler_seconds": DEFAULT_FILLER_SECONDS}


def _source_problem(src: dict) -> str | None:
    if src["mode"] == "mixed":
        if not src["video"] and not (src["filler"] and src["audio"]):
            return "Channel has no ready programs, and no filler clips plus music"
        return None
    if not src["video"]:
        return "Channel has no ready videos"
    if src["mode"] == "separate_audio" and not src["audio"]:
        return "Channel has no ready audio tracks"
    return None


def _has_filler(src: dict) -> bool:
    return bool(src["filler"] and src["audio"] and src["filler_seconds"] > 0)


def next_mixed_slot(src: dict, phase: str | None, program_idx: int) -> tuple[str, int]:
    """Mixed channel sequencing: program, filler block, program, filler block...
    phase is what just finished (None at start). Returns (next_phase, program_idx);
    program_idx is the program to play next. With no programs only filler plays,
    with no filler (or no music) programs play back to back."""
    has_programs, has_filler = bool(src["video"]), _has_filler(src)
    if phase == "program":
        program_idx += 1
        if has_filler:
            return "filler", program_idx
    elif phase is None and not has_programs:
        return "filler", program_idx
    if phase == "filler" and not has_programs:
        return "filler", program_idx
    return "program", program_idx % max(len(src["video"]), 1)


def _write_concat(path: Path, files: list[str]):
    with open(path, "w") as f:
        for media in files:
            safe_path = media.replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")


class _Channel:
    def __init__(self, playlist_id: int, get_files: Callable[[], list[str]]):
        self.playlist_id = playlist_id
        self.get_files = get_files
        self.stop_event = threading.Event()
        self.process: subprocess.Popen | None = None
        self.restarts = 0
        self.last_exit: int | None = None
        self.logger = _RotatingWriter(log_file(playlist_id))
        self.phase: str | None = None   # mixed channels: "program" or "filler"
        self.program_idx = 0
        self.block = 0
        self._fresh = True             # clear old HLS files only on the first start
        self.thread = threading.Thread(target=self._supervise, daemon=True,
                                       name=f"stream-{playlist_id}")

    # --- process control ---
    def _prepare(self, src: dict) -> list[str]:
        stream_dir = Path(HLS_PATH) / f"playlist_{self.playlist_id}"
        stream_dir.mkdir(parents=True, exist_ok=True)
        if self._fresh:
            self._clear(stream_dir)
            self._fresh = False
        out = stream_dir / "index.m3u8"
        video_concat = stream_dir / "playlist.txt"
        if src["mode"] == "mixed":
            if self.phase == "filler":
                clips = list(src["filler"])
                random.shuffle(clips)
                music = list(src["audio"])
                k = self.block % len(music)   # start each block on the next song
                _write_concat(video_concat, clips)
                audio_concat = stream_dir / "audio.txt"
                _write_concat(audio_concat, music[k:] + music[:k])
                return _build_separate_audio_cmd(video_concat, audio_concat, stream_dir, out,
                                                 duration=src["filler_seconds"])
            _write_concat(video_concat, [src["video"][self.program_idx]])
            return _build_cmd(video_concat, stream_dir, out, loop=False)
        _write_concat(video_concat, src["video"])
        if src["mode"] == "separate_audio":
            audio_concat = stream_dir / "audio.txt"
            _write_concat(audio_concat, src["audio"])
            return _build_separate_audio_cmd(video_concat, audio_concat, stream_dir, out)
        return _build_cmd(video_concat, stream_dir, out)

    @staticmethod
    def _clear(stream_dir: Path):
        for pattern in ("*.ts", "*.m3u8"):
            for f in stream_dir.glob(pattern):
                try:
                    f.unlink()
                except FileNotFoundError:
                    pass
                except OSError as e:
                    log.warning("Could not remove old HLS file %s: %s", f, e)

    def _spawn(self, src: dict):
        cmd = self._prepare(src)
        extra = (f", {len(src['audio'])} audio tracks"
                 if src["mode"] == "separate_audio" else "")
        if src["mode"] == "mixed":
            extra = (f", now {self.phase} block #{self.block}"
                     f" ({len(src['filler'])} filler clips, {len(src['audio'])} tracks,"
                     f" {src['filler_seconds'] / 60:g} min)" if self.phase == "filler"
                     else f", now program {self.program_idx + 1} of {len(src['video'])}")
        self.logger.write(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} starting ffmpeg "
                          f"(mode {src['mode']}: {len(src['video'])} videos{extra}, "
                          f"restart #{self.restarts}) ===")
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True, errors="replace",
            preexec_fn=os.setsid,
        )
        proc = self.process
        threading.Thread(target=self._pump, args=(proc,), daemon=True).start()

    def _pump(self, proc: subprocess.Popen):
        for line in proc.stderr:
            self.logger.write(line.rstrip("\n"))

    def _kill(self):
        proc = self.process
        if not proc or proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=10)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            log.warning("ffmpeg for channel %s ignored SIGTERM, killing", self.playlist_id)
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _supervise(self):
        backoff = BACKOFF_START
        while not self.stop_event.is_set():
            try:
                files = _normalize_source(self.get_files())
            except Exception:
                log.exception("Channel %s: could not load playlist", self.playlist_id)
                files = _normalize_source([])
            problem = _source_problem(files)
            if problem:
                self.logger.write(f"{problem}; waiting before retry")
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
                continue
            if files["mode"] == "mixed" and self.phase is None:
                self.phase, self.program_idx = next_mixed_slot(files, None, 0)
            elif files["mode"] == "mixed":
                # The lists may have changed since the last slot; stay in range.
                if self.phase == "program" and not files["video"]:
                    self.phase = "filler"
                elif self.phase == "filler" and not _has_filler(files):
                    self.phase = "program"
                self.program_idx %= max(len(files["video"]), 1)
            started = time.monotonic()
            try:
                self._spawn(files)
            except OSError as e:
                self.logger.write(f"Could not start ffmpeg: {e}")
                log.error("Channel %s: could not start ffmpeg: %s", self.playlist_id, e)
            else:
                while self.process.poll() is None and not self.stop_event.is_set():
                    self.stop_event.wait(1)
                if self.stop_event.is_set():
                    break
                self.last_exit = self.process.returncode
                if files["mode"] == "mixed" and self.last_exit == 0:
                    # Slot finished normally: go straight to the next one.
                    if self.phase == "filler":
                        self.block += 1
                    self.phase, self.program_idx = next_mixed_slot(
                        files, self.phase, self.program_idx)
                    self.logger.write(f"Slot finished; next: {self.phase}")
                    backoff = BACKOFF_START
                    continue
                msg = f"ffmpeg exited with code {self.last_exit}"
                self.logger.write(msg)
                log.warning("Channel %s: %s", self.playlist_id, msg)
            if time.monotonic() - started >= STABLE_SECONDS:
                backoff = BACKOFF_START
            self.restarts += 1
            self.logger.write(f"Restarting in {backoff:.0f}s")
            self.stop_event.wait(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
        self._kill()
        self.logger.write(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} stopped ===")
        self.logger.close()

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self._kill()
        self.thread.join(timeout=15)


def start_playlist_stream(playlist_id: int, get_files: Callable[[], list[str]]) -> str:
    """Start (or restart) a supervised stream. get_files is called on every
    (re)start so playlist edits are picked up after a crash."""
    problem = _source_problem(_normalize_source(get_files()))
    if problem:
        raise ValueError(problem)
    stop_playlist_stream(playlist_id)
    ch = _Channel(playlist_id, get_files)
    with _lock:
        running_processes[playlist_id] = ch
    ch.start()
    return str(Path(HLS_PATH) / f"playlist_{playlist_id}" / "index.m3u8")


def stop_playlist_stream(playlist_id: int):
    with _lock:
        ch = running_processes.pop(playlist_id, None)
    if ch:
        ch.stop()


def stream_status(playlist_id: int) -> dict:
    ch = running_processes.get(playlist_id)
    if not ch:
        return {"running": False}
    alive = ch.process is not None and ch.process.poll() is None
    return {"running": True, "ffmpeg_alive": alive, "restarts": ch.restarts,
            "last_exit_code": ch.last_exit, "slot": ch.phase}


def read_log_tail(playlist_id: int, lines: int = 100) -> list[str]:
    path = log_file(playlist_id)
    if not path.exists():
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return [l.rstrip("\n") for l in deque(f, maxlen=lines)]


def stop_all():
    for pid in list(running_processes):
        stop_playlist_stream(pid)
