"""Music rotation (repeat protection, shuffle, whole-song blocks) and play tracking."""
import random

from app.services import playtrack
from app.services.rotation import plan_block
from app.services.hls import plan_music, _normalize_source, _build_separate_audio_cmd


def pool(n, dur=100):
    return [{"id": i, "duration": dur} for i in range(1, n + 1)]


def ids(tracks):
    return [t["id"] for t in tracks]


def played(*mids, start=0.0, step=100.0, outcome="natural"):
    """History rows, newest first, for songs played in the given order."""
    rows = [{"media_id": m, "started_at": start + i * step, "outcome": outcome}
            for i, m in enumerate(mids)]
    return list(reversed(rows))


# ---------- whole songs ----------

def test_block_uses_whole_songs_nearest_target():
    p = [{"id": 1, "duration": 200}, {"id": 2, "duration": 200}, {"id": 3, "duration": 200}]
    # 500 s target: 2 songs = 400 (100 short) vs 3 songs = 600 (100 over) -> nearest wins, ties keep fewer
    assert ids(plan_block(p, [], 500, gap_minutes=0, now=0)) == [1, 2]
    assert ids(plan_block(p, [], 550, gap_minutes=0, now=0)) == [1, 2, 3]


def test_song_longer_than_block_still_plays_whole():
    p = [{"id": 1, "duration": 2400}, {"id": 2, "duration": 100}]
    assert ids(plan_block(p, [], 1800, gap_minutes=0, now=0)) == [1]


def test_unknown_duration_is_planned_but_never_loops_forever():
    p = [{"id": 1, "duration": None}]
    out = plan_block(p, [], 3600, gap_tracks=0, gap_minutes=0, now=0)
    assert 1 <= len(out) <= 500


# ---------- order, repeat protection ----------

def test_order_continues_after_last_natural_song():
    assert ids(plan_block(pool(5), played(1, 2), 260, gap_tracks=0, gap_minutes=0, now=1000)) == [3, 4, 5]


def test_cut_song_is_replayed_from_start():
    recent = played(1, 2) 
    recent.insert(0, {"media_id": 3, "started_at": 300, "outcome": "cut"})
    assert ids(plan_block(pool(5), recent, 100, gap_tracks=0, gap_minutes=0, now=400))[0] == 3


def test_repeat_gap_tracks_blocks_recent_songs():
    # 4 songs, gap 10 -> capped at 3, so a block cycles all four before repeating
    out = plan_block(pool(4), [], 800, shuffle=True, gap_tracks=10, gap_minutes=0, now=0,
                     rng=random.Random(1))
    for i in range(len(out) - 3):
        assert len(set(ids(out[i:i + 4]))) == 4


def test_repeat_gap_minutes():
    # song 1 played 30 min ago, gap 60 min -> skipped while others are eligible
    recent = [{"media_id": 1, "started_at": 0, "outcome": "natural"}]
    for seed in range(20):
        first = plan_block(pool(3), recent, 100, shuffle=True, gap_tracks=0, gap_minutes=60,
                           now=1800, rng=random.Random(seed))
        assert first[0]["id"] != 1


def test_everything_blocked_falls_back_to_least_recent():
    recent = played(2, 3, 1, start=0, step=60)   # 1 is newest, 2 oldest
    out = plan_block(pool(3), recent, 100, shuffle=True, gap_tracks=0, gap_minutes=600, now=200)
    assert ids(out) == [2]


def test_shuffle_varies_and_respects_pool():
    seen = {tuple(ids(plan_block(pool(8), [], 300, shuffle=True, gap_minutes=0, now=0,
                                 rng=random.Random(s)))) for s in range(10)}
    assert len(seen) > 1
    assert all(set(t) <= set(range(1, 9)) for t in seen)


def test_plan_music_reads_rotation_settings():
    src = _normalize_source({"mode": "separate_audio", "video": ["v"], "audio": ["a1", "a2", "a3"],
                             "audio_meta": [{"id": 1, "title": "A", "duration": 100},
                                            {"id": 2, "title": "B", "duration": 100},
                                            {"id": 3, "title": "C", "duration": 100}],
                             "rotation": {"shuffle": False, "gap_tracks": 0, "gap_minutes": 0},
                             "recent": [{"media_id": 1, "started_at": 0, "outcome": "natural"}]})
    out = plan_music(src, 200, now=500)
    assert [t["path"] for t in out] == ["a2", "a3"]


def test_audio_is_not_looped_and_ends_block():
    from pathlib import Path
    cmd = _build_separate_audio_cmd(Path("v.txt"), Path("a.txt"), Path("/tmp"), Path("/tmp/o.m3u8"))
    v, a = cmd.index("v.txt"), cmd.index("a.txt")
    assert cmd[v - 6:v - 1].count("-stream_loop") == 1          # video loops
    assert "-stream_loop" not in cmd[v + 1:a]                    # audio plays once
    assert "-shortest" in cmd and "-t" not in cmd


# ---------- play tracker ----------

class Rec:
    def __init__(self):
        self.rows = {}

    def started(self, pid, song, mode, at):
        k = len(self.rows) + 1
        self.rows[k] = {"id": song["id"], "start": at, "outcome": "playing"}
        return k

    def finished(self, k, outcome, played, reason, at):
        self.rows[k].update(outcome=outcome, played=played, reason=reason, end=at)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def test_tracker_natural_and_cut():
    clock, rec = Clock(), Rec()
    tr = playtrack.PlayTracker(1, "separate_audio", pool(3, 100), rec, clock=clock)
    tr.start()
    clock.t += 150
    tr.tick()
    assert [r["outcome"] for r in rec.rows.values()] == ["natural", "playing"]
    clock.t += 20   # song 2 is 70 s in -> stopping now cuts it
    tr.finish(False, "channel stopped or restarted")
    r2 = rec.rows[2]
    assert r2["outcome"] == "cut" and r2["played"] == 70 and r2["reason"].startswith("channel")
    assert len(rec.rows) == 2


def test_tracker_completed_run_marks_all_natural():
    clock, rec = Clock(), Rec()
    tr = playtrack.PlayTracker(1, "mixed", pool(3, 100), rec, clock=clock)
    tr.start()
    clock.t += 299   # wall clock a little behind ffmpeg; it exited normally at the end
    tr.finish(True)
    assert [r["outcome"] for r in rec.rows.values()] == ["natural"] * 3


def test_tracker_end_within_slack_counts_natural():
    clock, rec = Clock(), Rec()
    tr = playtrack.PlayTracker(1, "mixed", pool(1, 100), rec, clock=clock)
    tr.start()
    clock.t += 99
    tr.finish(False, "ffmpeg exited with code 1")
    assert rec.rows[1]["outcome"] == "natural"


def test_tracker_survives_recorder_errors():
    class Bad:
        def started(self, *a):
            raise RuntimeError("db down")

        def finished(self, *a):
            raise RuntimeError("db down")
    tr = playtrack.PlayTracker(1, "mixed", pool(2), Bad(), clock=Clock())
    tr.start()
    tr.tick()
    tr.finish(False, "x")
