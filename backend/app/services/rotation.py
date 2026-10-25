"""Music rotation: which songs play next on a channel.

Pure functions (no database, no ffmpeg), so the rules are easy to test:
- disabled tracks never play (the loader already leaves them out of the pool);
- repeat protection: a track that finished within the last `gap_tracks` songs, or
  started within the last `gap_minutes` minutes, is skipped while anything else is
  eligible. If everything is blocked, the least recently played track goes next;
- shuffle picks at random among eligible tracks; otherwise the list plays in order,
  continuing after the last song that played to its end (a song that was cut off
  by a restart is therefore played again from the start);
- whole songs only: a block is filled with whole songs whose total is as close as
  possible to the target length (always at least one song), so nothing is cut.

`recent` is the channel's play history, newest first, as dicts with
"media_id", "started_at" (epoch seconds) and "outcome" ("natural", "cut", "playing").
Cut plays do not count for repeat protection.
"""
import random
from typing import Sequence

UNKNOWN_SECONDS = 180.0   # planning length for a track whose duration is unknown
MAX_TRACKS_PER_BLOCK = 500


def track_seconds(track: dict) -> float:
    d = track.get("duration")
    return float(d) if d and d > 0 else UNKNOWN_SECONDS


def _counted(recent: Sequence[dict]) -> list[dict]:
    return [r for r in recent if r.get("outcome") != "cut" and r.get("media_id") is not None]


def plan_block(pool: Sequence[dict], recent: Sequence[dict], target_seconds: float, *,
               shuffle: bool = False, gap_tracks: int = 10, gap_minutes: int = 60,
               now: float, rng: random.Random | None = None) -> list[dict]:
    """Choose whole songs from `pool` (list order, dicts with "id" and "duration")
    totalling as close as possible to `target_seconds`. Returns the chosen tracks."""
    if not pool:
        return []
    rng = rng or random.Random()
    ids = [t["id"] for t in pool]
    by_id = {t["id"]: t for t in pool}
    history = _counted(recent)   # newest first; grows as we pick
    picks: list[dict] = []
    total = 0.0
    while len(picks) < MAX_TRACKS_PER_BLOCK:
        track = by_id[_next_id(ids, history, shuffle=shuffle, gap_tracks=gap_tracks,
                               gap_minutes=gap_minutes, now=now + total, rng=rng)]
        length = track_seconds(track)
        if picks and total + length - target_seconds >= target_seconds - total:
            break   # stopping here lands closer to the target than adding this song
        picks.append(track)
        history.insert(0, {"media_id": track["id"], "started_at": now + total,
                           "outcome": "natural"})
        total += length
        if total >= target_seconds:
            break
    return picks


def _next_id(ids: list, history: list[dict], *, shuffle: bool, gap_tracks: int,
             gap_minutes: int, now: float, rng: random.Random):
    unique = list(dict.fromkeys(ids))
    blocked = set()
    # Never block every track by count alone: with 5 songs, at most 4 are held back.
    n = max(0, min(gap_tracks or 0, len(unique) - 1))
    for r in history[:n]:
        blocked.add(r["media_id"])
    if gap_minutes and gap_minutes > 0:
        cutoff = now - gap_minutes * 60
        for r in history:
            if r["started_at"] >= cutoff:
                blocked.add(r["media_id"])
    eligible = [i for i in unique if i not in blocked]
    if not eligible:
        # Everything played recently: take the one that has waited longest.
        last_seen = {}
        for r in reversed(history):   # oldest first, so newer plays overwrite
            last_seen[r["media_id"]] = r["started_at"]
        oldest = min(last_seen.get(i, float("-inf")) for i in unique)
        eligible = [i for i in unique if last_seen.get(i, float("-inf")) == oldest]
        if not shuffle:
            # In order mode keep the list order among the tied ones.
            return _in_order(ids, history, set(eligible))
    if shuffle:
        return rng.choice(eligible)
    return _in_order(ids, history, set(eligible))


def _in_order(ids: list, history: list[dict], allowed: set):
    """The first allowed track after the last one that played to its end."""
    start = 0
    for r in history:
        if r["media_id"] in ids:
            start = ids.index(r["media_id"]) + 1
            break
    for k in range(len(ids)):
        i = ids[(start + k) % len(ids)]
        if i in allowed:
            return i
    return ids[start % len(ids)]
