"""ffmpeg stream management with supervision, auto-restart and per-channel logs."""
import logging
import os
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


def _build_cmd(concat_file: Path, stream_dir: Path, output_m3u8: Path) -> list[str]:
    return [
        FFMPEG_BIN, "-hide_banner", "-loglevel", "warning",
        "-re", "-f", "concat", "-safe", "0", "-stream_loop", "-1",
        "-i", str(concat_file),
        "-vf", "fps=30,format=yuv420p",
        "-af", "aresample=44100",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-profile:v", "main", "-crf", "22", "-g", "60", "-keyint_min", "60",
        "-sc_threshold", "0", "-force_key_frames", "expr:gte(t,n_forced*2)",
        "-vsync", "cfr",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-f", "hls", "-hls_time", "6", "-hls_list_size", "10",
        "-hls_flags", "delete_segments+append_list+omit_endlist+independent_segments",
        "-hls_segment_filename", str(stream_dir / "segment_%03d.ts"),
        str(output_m3u8),
    ]


class _Channel:
    def __init__(self, playlist_id: int, get_files: Callable[[], list[str]]):
        self.playlist_id = playlist_id
        self.get_files = get_files
        self.stop_event = threading.Event()
        self.process: subprocess.Popen | None = None
        self.restarts = 0
        self.last_exit: int | None = None
        self.logger = _RotatingWriter(log_file(playlist_id))
        self.thread = threading.Thread(target=self._supervise, daemon=True,
                                       name=f"stream-{playlist_id}")

    # --- process control ---
    def _prepare(self, media_files: list[str]) -> tuple[Path, Path, Path]:
        stream_dir = Path(HLS_PATH) / f"playlist_{self.playlist_id}"
        stream_dir.mkdir(parents=True, exist_ok=True)
        for pattern in ("*.ts", "*.m3u8"):
            for f in stream_dir.glob(pattern):
                try:
                    f.unlink()
                except FileNotFoundError:
                    pass
                except OSError as e:
                    log.warning("Could not remove old HLS file %s: %s", f, e)
        concat_file = stream_dir / "playlist.txt"
        with open(concat_file, "w") as f:
            for media in media_files:
                safe_path = media.replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")
        return concat_file, stream_dir, stream_dir / "index.m3u8"

    def _spawn(self, media_files: list[str]):
        concat_file, stream_dir, out = self._prepare(media_files)
        self.logger.write(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} starting ffmpeg "
                          f"({len(media_files)} files, restart #{self.restarts}) ===")
        self.process = subprocess.Popen(
            _build_cmd(concat_file, stream_dir, out),
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
                files = self.get_files()
            except Exception:
                log.exception("Channel %s: could not load playlist", self.playlist_id)
                files = []
            if not files:
                self.logger.write("Channel has no media; waiting before retry")
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
                continue
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
    if not get_files():
        raise ValueError("No media files provided")
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
            "last_exit_code": ch.last_exit}


def read_log_tail(playlist_id: int, lines: int = 100) -> list[str]:
    path = log_file(playlist_id)
    if not path.exists():
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return [l.rstrip("\n") for l in deque(f, maxlen=lines)]


def stop_all():
    for pid in list(running_processes):
        stop_playlist_stream(pid)
