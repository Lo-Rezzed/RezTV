"""Conform-on-upload: only files that already match the station spec exactly skip re-encoding."""
import shutil
import subprocess

import pytest

from app.services import convert

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def details(r="30/1", avg="30/1", size=(convert.WIDTH, convert.HEIGHT), codec="h264",
            pix="yuv420p", fmt="mov,mp4,m4a,3gp,3g2,mj2"):
    return {"format": {"format_name": fmt},
            "streams": [{"codec_type": "video", "codec_name": codec, "pix_fmt": pix,
                         "width": size[0], "height": size[1], "sample_aspect_ratio": "1:1",
                         "r_frame_rate": r, "avg_frame_rate": avg},
                        {"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100",
                         "channels": 2}]}


def test_exact_match_is_only_remuxed():
    plan = convert.conform_plan(details(), "a.mp4", skip_matching=True)
    assert plan["action"] == "remux" and not plan["converted"]


def test_equivalent_fraction_counts_as_30():
    assert convert.conform_plan(details(avg="15360/512"), "a.mp4", True)["action"] == "remux"


@pytest.mark.parametrize("kw,expect", [
    ({"r": "30000/1001", "avg": "30000/1001"}, "frame rate 29.970"),  # iMovie 29.97
    ({"r": "30/1", "avg": "400/19"}, "variable frame rate"),          # VFR export
    ({"r": "60/1", "avg": "30/1"}, "variable frame rate"),
    ({"r": "25/1", "avg": "25/1"}, "frame rate 25.000"),
    ({"r": "0/0", "avg": "0/0"}, "frame rate unknown"),
    ({"size": (1920, 1080)}, "size"),
    ({"pix": "yuv422p"}, "pixel format"),
    ({"codec": "hevc"}, "video codec"),
])
def test_off_spec_video_is_reencoded(kw, expect):
    plan = convert.conform_plan(details(**kw), "a.mp4", skip_matching=True)
    assert plan["action"] == "reencode" and plan["converted"]
    assert expect in plan["reason"]


def test_skip_disabled_always_reencodes():
    plan = convert.conform_plan(details(), "a.mp4", skip_matching=False)
    assert plan["action"] == "reencode" and "CONVERT_SKIP_MATCHING" in plan["reason"]


def test_no_probe_details_reencodes():
    assert convert.conform_plan({}, "a.mp4", skip_matching=True)["action"] == "reencode"


def _make(path, rate="30", vf=None, vfr=False):
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
           "-i", f"testsrc=size={convert.WIDTH}x{convert.HEIGHT}:rate={rate}",
           "-f", "lavfi", "-i", "sine=sample_rate=44100", "-ac", "2", "-c:a", "aac", "-t", "2"]
    if vf:
        cmd += ["-vf", vf]
    if vfr:
        cmd += ["-fps_mode", "vfr"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return str(path)


def _rates(path):
    v = [s for s in convert.probe_streams(path)["streams"] if s["codec_type"] == "video"][0]
    return v["r_frame_rate"], v["avg_frame_rate"]


@needs_ffmpeg
@pytest.mark.parametrize("kind", ["ntsc", "vfr"])
def test_real_off_spec_files_are_conformed_to_cfr_30(tmp_path, kind):
    if kind == "ntsc":
        src = _make(tmp_path / "imovie.mp4", rate="30000/1001")
    else:
        src = _make(tmp_path / "vfr.mp4", vf="setpts='if(lt(N,30),N,N*1.5)/30/TB'", vfr=True)
    plan = convert.conform_plan(convert.probe_streams(src), src, skip_matching=True)
    assert plan["action"] == "reencode", plan
    dst = str(tmp_path / "out.mp4")
    subprocess.run(convert.build_command(src, dst, convert.probe(src), False), check=True)
    assert _rates(dst) == ("30/1", "30/1")
    assert convert.conform_plan(convert.probe_streams(dst), dst, skip_matching=True)["action"] == "remux"
