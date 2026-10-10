import os
import subprocess
import signal
from pathlib import Path

HLS_PATH = os.getenv("HLS_PATH", "/app/hls")
MEDIA_PATH = os.getenv("MEDIA_PATH", "/app/media")

running_processes = {}

def start_playlist_stream(playlist_id: int, media_files: list[str]):
    if not media_files:
        raise ValueError("No media files provided")

    stream_dir = Path(HLS_PATH) / f"playlist_{playlist_id}"
    stream_dir.mkdir(parents=True, exist_ok=True)

    # Clean old files
    for f in stream_dir.glob("*.ts"):
        try:
            f.unlink()
        except:
            pass
    for f in stream_dir.glob("*.m3u8"):
        try:
            f.unlink()
        except:
            pass

    # Create concat list
    concat_file = stream_dir / "playlist.txt"
    with open(concat_file, "w") as f:
        for media in media_files:
            safe_path = media.replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    output_m3u8 = stream_dir / "index.m3u8"

    cmd = [
        "ffmpeg",
        "-re",
        "-f", "concat",
        "-safe", "0",
        "-stream_loop", "-1",
        "-i", str(concat_file),

        # Strong normalization
        "-vf", "fps=30,format=yuv420p",
        "-af", "aresample=44100",

        # Video
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-profile:v", "main",
        "-crf", "22",
        "-g", "60",
        "-keyint_min", "60",
        "-sc_threshold", "0",
        "-force_key_frames", "expr:gte(t,n_forced*2)",
        "-vsync", "cfr",

        # Audio
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-ac", "2",

        # HLS
        "-f", "hls",
        "-hls_time", "6",
        "-hls_list_size", "10",
        "-hls_flags", "delete_segments+append_list+omit_endlist+independent_segments",
        "-hls_segment_filename", str(stream_dir / "segment_%03d.ts"),
        str(output_m3u8)
    ]

    stop_playlist_stream(playlist_id)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid
    )

    running_processes[playlist_id] = process
    return str(output_m3u8)


def stop_playlist_stream(playlist_id: int):
    process = running_processes.get(playlist_id)
    if process:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except Exception:
            pass
        running_processes.pop(playlist_id, None)
