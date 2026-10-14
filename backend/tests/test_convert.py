"""Run with: cd backend && pip install pytest && pytest  (needs ffmpeg/ffprobe)."""
import shutil
import subprocess

import pytest

from app.services import convert

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def make(path, size="320x240", rate=30, vcodec="libx264", pix="yuv420p", audio=True, ar=44100):
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
           "-i", f"testsrc=size={size}:rate={rate}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=sample_rate={ar}", "-ac", "2", "-c:a", "aac"]
    cmd += ["-t", "1", "-c:v", vcodec, "-pix_fmt", pix, str(path)]
    subprocess.run(cmd, check=True)
    return str(path)


def match(path):
    return convert.station_match(convert.probe_streams(path), path)


def test_matching_file_is_detected(tmp_path):
    ok, why = match(make(tmp_path / "a.mp4"))
    assert ok, why


@pytest.mark.parametrize("kw,expect", [
    ({"size": "640x480"}, "size"),
    ({"rate": 25}, "frame rate"),
    ({"pix": "yuv444p"}, "pixel format"),
    ({"audio": False}, "audio streams"),
    ({"ar": 48000}, "Hz"),
    ({"vcodec": "mpeg4"}, "video codec"),
])
def test_mismatches_are_reencoded(tmp_path, kw, expect):
    ok, why = match(make(tmp_path / "b.mp4", **kw))
    assert not ok and expect in why


def test_mkv_container_is_reencoded(tmp_path):
    ok, why = match(make(tmp_path / "c.mkv"))
    assert not ok


def test_remux_output_still_matches(tmp_path):
    src = make(tmp_path / "d.mp4")
    dst = str(tmp_path / "out.mp4")
    subprocess.run(convert.build_remux_command(src, dst), check=True)
    ok, why = match(dst)
    assert ok, why


@pytest.mark.parametrize("kw", [{"ar": 48000}, {"audio": False}])
def test_audio_only_fix_copies_video(tmp_path, kw):
    src = make(tmp_path / "e.mp4", **kw)
    v_ok, a_ok, _ = convert.station_check(convert.probe_streams(src), src)
    assert v_ok and not a_ok
    dst = str(tmp_path / "out.mp4")
    info = convert.probe(src)
    subprocess.run(convert.build_audio_fix_command(src, dst, info), check=True)
    ok, why = match(dst)
    assert ok, why
