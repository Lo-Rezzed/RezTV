"""Background conversion of uploads to the RezTV station standard.

Every upload is re-encoded once, right after it is accepted, to one format so the
channel stream never meets a file it can't join: same size, frame rate, codecs and
audio layout. Settings come from environment variables (see .env.example).
"""
import logging
import math
import os
import queue
import re
import subprocess
import threading

log = logging.getLogger("reztv.convert")

FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.getenv("FFPROBE_BIN", "ffprobe")


def _parse_resolution(value: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{2,5})\s*[xX:]\s*(\d{2,5})\s*", value or "")
    if not m:
        raise RuntimeError(f"STATION_RESOLUTION must look like 1920x1080, got {value!r}")
    w, h = int(m.group(1)), int(m.group(2))
    if w % 2 or h % 2:
        raise RuntimeError("STATION_RESOLUTION width and height must be even numbers")
    return w, h


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


WIDTH, HEIGHT = _parse_resolution(os.getenv("STATION_RESOLUTION", "1920x1080"))
FPS = int(os.getenv("STATION_FPS", "30"))
LOUDNORM = _bool("STATION_LOUDNORM", True)
LOUDNORM_TARGET = float(os.getenv("STATION_LOUDNORM_TARGET", "-16"))
GIF_MIN_SECONDS = float(os.getenv("GIF_MIN_SECONDS", "30"))
KEEP_ORIGINALS = _bool("KEEP_ORIGINALS", False)
CONVERT_PRESET = os.getenv("CONVERT_PRESET", "veryfast")
CONVERT_CRF = os.getenv("CONVERT_CRF", "20")
CONVERT_TIMEOUT = int(os.getenv("CONVERT_TIMEOUT_SECONDS", "21600"))  # 6 hours


def probe(path: str, kind: str = "video") -> dict:
    """Return {'has_video', 'has_audio', 'duration'}; raise ValueError if unreadable.
    kind="video" needs a video stream; kind="audio" needs an audio stream."""
    try:
        r = subprocess.run([FFPROBE_BIN, "-v", "error",
                            "-show_entries", "stream=codec_type:format=duration",
                            "-of", "default=noprint_wrappers=1", path],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ValueError(f"could not check file: {e}")
    if r.returncode != 0:
        raise ValueError(f"not a readable {kind} file")
    has_video = "codec_type=video" in r.stdout
    has_audio = "codec_type=audio" in r.stdout
    if kind == "audio" and not has_audio:
        raise ValueError("not a readable audio file")
    if kind != "audio" and not has_video:
        raise ValueError("not a readable video file")
    m = re.search(r"duration=([0-9.]+)", r.stdout)
    return {"has_video": has_video, "has_audio": has_audio,
            "duration": float(m.group(1)) if m else None}


def build_audio_command(src: str, dst: str) -> list[str]:
    """Music for separate-audio channels: AAC, 44.1 kHz stereo, volume evened out.
    Cover art and other non-audio streams are dropped. Stored in Matroska (.mka):
    ffmpeg's looping concat input can't rewind a list of audio-only MP4/M4A files,
    but loops .mka cleanly."""
    cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
           "-map", "0:a:0", "-vn", "-sn", "-dn", "-map_metadata", "-1"]
    af = "aresample=44100"
    if LOUDNORM:
        af = f"loudnorm=I={LOUDNORM_TARGET}:TP=-1.5:LRA=11,aresample=44100"
    cmd += ["-af", af, "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-f", "matroska", dst]
    return cmd


def build_command(src: str, dst: str, info: dict, is_gif: bool) -> list[str]:
    cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y"]
    loops = 0
    if is_gif:
        dur = info.get("duration") or 0
        loops = (math.ceil(GIF_MIN_SECONDS / dur) - 1) if dur > 0 else -1
        if loops > 0 or loops == -1:
            cmd += ["-stream_loop", str(loops)]
    cmd += ["-i", src]
    has_audio = info["has_audio"] and not is_gif
    if not has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    vf = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:flags=lanczos,"
          f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
          f"fps={FPS},format=yuv420p")
    cmd += ["-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0", "-vf", vf]
    if has_audio and LOUDNORM:
        cmd += ["-af", f"loudnorm=I={LOUDNORM_TARGET}:TP=-1.5:LRA=11,aresample=44100"]
    cmd += ["-c:v", "libx264", "-preset", CONVERT_PRESET, "-crf", str(CONVERT_CRF),
            "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-g", str(FPS * 2), "-keyint_min", str(FPS * 2), "-sc_threshold", "0",
            "-fps_mode", "cfr",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart"]
    if is_gif and loops == -1:
        cmd += ["-t", str(GIF_MIN_SECONDS)]
    if not has_audio:
        cmd += ["-shortest"]
    cmd += [dst]
    return cmd


class Converter:
    """One worker thread; converts one file at a time so the stream keeps CPU headroom."""

    def __init__(self, session_factory, media_model):
        self.session_factory = session_factory
        self.Media = media_model
        self.q: "queue.Queue[int]" = queue.Queue()
        self._started = False
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._run, daemon=True, name="converter").start()
        # Re-queue anything interrupted by a restart.
        db = self.session_factory()
        try:
            for m in db.query(self.Media).filter(
                    self.Media.status.in_(["pending", "converting"])).order_by(self.Media.id):
                m.status = "pending"
                self.q.put(m.id)
            db.commit()
        finally:
            db.close()

    def enqueue(self, media_id: int):
        self.q.put(media_id)

    def _run(self):
        while True:
            mid = self.q.get()
            try:
                self.convert(mid)
            except Exception:
                log.exception("Conversion crashed for media %s", mid)

    def _set(self, mid, **fields):
        db = self.session_factory()
        try:
            m = db.query(self.Media).filter(self.Media.id == mid).first()
            if not m:
                return None
            for k, v in fields.items():
                setattr(m, k, v)
            db.commit()
            return {"src": m.original_path, "dst": m.filepath,
                    "kind": getattr(m, "kind", None) or "video"}
        finally:
            db.close()

    def convert(self, mid: int):
        paths = self._set(mid, status="converting", error=None)
        if not paths:
            return  # deleted while waiting
        src, dst = paths["src"], paths["dst"]
        if not src or not os.path.exists(src):
            self._set(mid, status="failed", error="original upload is missing")
            return
        kind = paths["kind"]
        tmp = dst + (".part.mka" if kind == "audio" else ".part.mp4")
        try:
            info = probe(src, kind)
            if kind == "audio":
                cmd = build_audio_command(src, tmp)
            else:
                is_gif = src.lower().endswith(".gif")
                cmd = build_command(src, tmp, info, is_gif)
            log.info("Converting media %s: %s", mid, " ".join(cmd))
            r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                               timeout=CONVERT_TIMEOUT)
            if r.returncode != 0:
                raise ValueError((r.stderr or "ffmpeg failed").strip()[-500:])
            out = probe(tmp, kind)
            os.replace(tmp, dst)
        except (ValueError, OSError, subprocess.TimeoutExpired) as e:
            if os.path.exists(tmp):
                os.remove(tmp)
            log.warning("Conversion failed for media %s: %s", mid, e)
            self._set(mid, status="failed", error=str(e)[:500])
            return
        keep = KEEP_ORIGINALS
        if not keep:
            try:
                os.remove(src)
            except OSError as e:
                log.warning("Could not remove original %s: %s", src, e)
        if self._set(mid, status="ready", error=None, duration=out["duration"],
                     original_path=src if keep else None) is None:
            # Deleted while converting: clean up the result too.
            for p in (dst, src):
                if p and os.path.exists(p):
                    os.remove(p)
        log.info("Media %s ready (%.1fs)", mid, out["duration"] or 0)
