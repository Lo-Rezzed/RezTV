"""Audio round 2 API: library filters, enable/disable, lyrics tag, folder playlists,
rotation settings, play history, duration re-measuring, migrations and backups."""
import json
import shutil
import subprocess
import tarfile
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from test_admin_api import AUTH, client  # noqa: F401  (fixture)

from app import main
from app.core.database import Base
from app.models.media import Media
from app.models.playlist import Playlist, PlayHistory, playlist_audio, playlist_media
from app.services import backup
from app.services.convert import Converter

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@pytest.fixture
def api(client):  # noqa: F811
    db = main.SessionLocal()
    db.query(PlayHistory).delete()
    db.execute(playlist_audio.delete())
    db.execute(playlist_media.delete())
    db.query(Playlist).delete()
    db.commit()
    db.close()
    return client


def add(title, kind="audio", folder="Music", status="ready", duration=100.0, **kw):
    db = main.SessionLocal()
    m = Media(filename=f"{title}.mka", original_filename=f"{title}.mp3", title=title,
              filepath=f"/x/{title}", folder=folder, kind=kind, status=status,
              duration=duration, **kw)
    db.add(m)
    db.commit()
    mid = m.id
    db.close()
    return mid


def channel(api, **kw):
    r = api.post("/playlists", json={"name": "Radio", "mode": "separate_audio", **kw}, headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- library ----------

def test_kind_vocals_enabled_filters_and_title_sort(api):
    a = add("Zebra", vocals="vocals")
    b = add("apple", vocals="instrumental")
    c = add("Mango", enabled=False)
    add("Video clip", kind="video", folder="Filler")
    get = lambda **p: api.get("/media", params={"page": 1, **p}, headers=AUTH).json()
    assert [m["id"] for m in get(kind="audio", sort="title")["items"]] == [b, c, a]
    assert [m["title"] for m in get(kind="video")["items"]] == ["Video clip"]
    assert [m["id"] for m in get(kind="audio", vocals="vocals")["items"]] == [a]
    assert [m["id"] for m in get(kind="audio", vocals="untagged")["items"]] == [c]
    assert [m["id"] for m in get(kind="audio", enabled="false")["items"]] == [c]
    assert get(kind="audio", enabled="true")["total"] == 2
    assert [m["id"] for m in get(kind="audio", q="ang")["items"]] == [c]   # q still works
    assert api.get("/media", params={"kind": "gif"}, headers=AUTH).status_code == 400
    assert api.get("/media", params={"vocals": "loud"}, headers=AUTH).status_code == 400


def test_enable_disable_and_vocals_tag(api):
    mid = add("Song")
    r = api.put(f"/media/{mid}", json={"enabled": False, "vocals": "vocals"}, headers=AUTH).json()
    assert r["enabled"] is False and r["vocals"] == "vocals"
    r = api.put(f"/media/{mid}", json={"vocals": ""}, headers=AUTH).json()
    assert r["vocals"] is None and r["enabled"] is False          # other fields untouched
    assert api.put(f"/media/{mid}", json={"vocals": "rap"}, headers=AUTH).status_code == 422
    assert api.put(f"/media/{mid}", json={"enabled": True}, headers=AUTH).json()["enabled"] is True


def test_disabled_tracks_are_skipped_in_rotation(api):
    p = channel(api)
    ids = [add(t) for t in ("One", "Two", "Three")]
    for mid in ids:
        assert api.post(f"/playlists/{p['id']}/audio/{mid}", headers=AUTH).status_code == 200
    api.put(f"/media/{ids[1]}", json={"enabled": False}, headers=AUTH)
    files = main.playlist_files_loader(p["id"])()
    assert [m["id"] for m in files["audio_meta"]] == [ids[0], ids[2]]
    music = api.get(f"/playlists/{p['id']}/music", headers=AUTH).json()
    assert music["source"] == "list" and music["in_rotation"] == 2
    assert [t["in_rotation"] for t in music["tracks"]] == [True, False, True]
    assert music["total_seconds"] == 200
    # still listed on the channel's audio list, marked disabled
    audio = api.get(f"/playlists/{p['id']}/audio", headers=AUTH).json()
    assert [t["enabled"] for t in audio] == [True, False, True]


def test_folder_playlist_picks_up_new_tracks(api):
    add("Old", folder="Ambient")
    add("Elsewhere", folder="Other")
    p = channel(api, audio_folder="Ambient")
    assert p["audio_folder"] == "Ambient"
    loader = main.playlist_files_loader(p["id"])
    assert [m["title"] for m in loader()["audio_meta"]] == ["Old"]
    add("New upload", folder="Ambient")                          # joins automatically
    add("Converting", folder="Ambient", status="converting")     # not until it is ready
    add("Off", folder="Ambient", enabled=False)
    assert [m["title"] for m in loader()["audio_meta"]] == ["Old", "New upload"]
    music = api.get(f"/playlists/{p['id']}/music", headers=AUTH).json()
    assert music["source"] == "folder" and music["in_rotation"] == 2 and len(music["tracks"]) == 4
    # "" switches back to the hand-made list
    r = api.put(f"/playlists/{p['id']}", json={"audio_folder": ""}, headers=AUTH).json()
    assert r["audio_folder"] is None and loader()["audio_meta"] == []


def test_rotation_settings_round_trip(api):
    p = channel(api)
    assert (p["audio_shuffle"], p["repeat_gap_tracks"], p["repeat_gap_minutes"]) == (False, 10, 60)
    r = api.put(f"/playlists/{p['id']}", headers=AUTH,
                json={"audio_shuffle": True, "repeat_gap_tracks": 3, "repeat_gap_minutes": 0}).json()
    assert (r["audio_shuffle"], r["repeat_gap_tracks"], r["repeat_gap_minutes"]) == (True, 3, 0)
    rot = main.playlist_files_loader(p["id"])()["rotation"]
    assert rot == {"shuffle": True, "gap_tracks": 3, "gap_minutes": 0}
    assert api.put(f"/playlists/{p['id']}", json={"repeat_gap_tracks": -1},
                   headers=AUTH).status_code == 422
    listed = [c for c in api.get("/playlists").json() if c["id"] == p["id"]][0]
    assert listed["audio_shuffle"] is True


# ---------- play history ----------

def test_recorder_history_endpoint_and_recent_plays(api):
    p = channel(api, repeat_gap_tracks=1, repeat_gap_minutes=0)
    a, b = add("A", duration=60), add("B", duration=60)
    for mid in (a, b):
        api.post(f"/playlists/{p['id']}/audio/{mid}", headers=AUTH)
    rec = main.history_recorder
    t0 = datetime.now(timezone.utc).timestamp() - 200
    tok = rec.started(p["id"], {"id": a, "title": "A", "duration": 60}, "separate_audio", t0)
    rec.finished(tok, "natural", 60, None, t0 + 60)
    tok = rec.started(p["id"], {"id": b, "title": "B", "duration": 60}, "separate_audio", t0 + 60)
    rec.finished(tok, "cut", 12.5, "ffmpeg exited with code 1", t0 + 72.5)
    hist = api.get("/history", params={"playlist_id": p["id"]}, headers=AUTH).json()
    assert [(h["title"], h["outcome"]) for h in hist] == [("B", "cut"), ("A", "natural")]
    assert hist[0]["channel"] == "Radio" and hist[0]["played_seconds"] == 12.5
    assert hist[0]["reason"] == "ffmpeg exited with code 1"
    assert hist[0]["started_at"].endswith("+00:00")
    assert api.get("/history").status_code == 401
    # The loader hands recent plays to the rotation: B was cut, so it plays again next.
    files = main.playlist_files_loader(p["id"])()
    assert [r["media_id"] for r in files["recent"]] == [b, a]
    from app.services.hls import plan_music, _normalize_source
    songs = plan_music(_normalize_source(files), 60, now=t0 + 300)
    assert [s["id"] for s in songs] == [b]


def test_close_orphan_plays_and_prune(api, monkeypatch):
    db = main.SessionLocal()
    now = datetime.now(timezone.utc)
    db.add_all([PlayHistory(playlist_id=1, title="open", started_at=now, outcome="playing"),
                PlayHistory(playlist_id=1, title="ancient", started_at=now - timedelta(days=400),
                            outcome="natural")])
    db.commit()
    db.close()
    main.close_orphan_plays()
    db = main.SessionLocal()
    rows = db.query(PlayHistory).all()
    db.close()
    assert [(r.title, r.outcome, r.reason) for r in rows] == [("open", "cut", "server restarted")]


# ---------- durations ----------

def _bad_header_mp3(tmp_path):
    """An MP3 whose header-based duration is far off (a 3 s low-bitrate part followed by
    a 5 s high-bitrate part, no Xing header): metadata says ~33 s, it really is ~8 s."""
    parts = []
    for name, secs, rate in (("lo", 3, "32k"), ("hi", 5, "192k")):
        p = tmp_path / f"{name}.mp3"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"sine=duration={secs}", "-b:a", rate, "-write_xing", "0", str(p)], check=True)
        parts.append(p.read_bytes())
    out = tmp_path / "song.mp3"
    out.write_bytes(b"".join(parts))
    return out


@needs_ffmpeg
def test_converter_stores_duration_of_converted_file(tmp_path):
    src = _bad_header_mp3(tmp_path)
    from app.services.convert import probe
    assert probe(str(src), "audio")["duration"] > 20        # the misleading metadata
    eng = create_engine(f"sqlite:///{tmp_path}/c.db")
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    db = Session()
    m = Media(filename="song.mka", original_filename="song.mp3", filepath=str(tmp_path / "song.mka"),
              original_path=str(src), folder="Music", kind="audio", status="pending", duration=33.3)
    db.add(m)
    db.commit()
    mid = m.id
    db.close()
    Converter(Session, Media).convert(mid)
    db = Session()
    m = db.get(Media, mid)
    assert m.status == "ready" and m.duration_source == "measured"
    assert 7.8 < m.duration < 8.3
    db.close()


@needs_ffmpeg
def test_remeasure_fixes_metadata_durations(api, tmp_path):
    src = _bad_header_mp3(tmp_path)
    old = add("Wrong", duration=33.3)
    good = add("Measured", duration=99.0, duration_source="measured")
    gone = add("Gone", duration=10.0)
    db = main.SessionLocal()
    db.get(Media, old).filepath = str(src)
    db.commit()
    db.close()
    assert api.get("/media/remeasure-durations", headers=AUTH).json()["unmeasured"] == 2
    r = main.remeasure_durations()       # what the startup check runs
    assert r == {"checked": 2, "changed": 1, "missing": 1, "failed": 0}
    db = main.SessionLocal()
    m = db.get(Media, old)
    assert 7.8 < m.duration < 8.3 and m.duration_source == "measured"
    assert db.get(Media, good).duration == 99.0          # measured ones left alone
    assert db.get(Media, gone).duration_source is None
    db.close()
    assert api.get(f"/media", params={"page": 1, "q": "Wrong"},
                   headers=AUTH).json()["items"][0]["duration_measured"] is True


def test_remeasure_endpoint_runs_in_background(api, monkeypatch):
    seen = []
    monkeypatch.setattr(main, "remeasure_durations",
                        lambda only_unmeasured=True: seen.append(only_unmeasured) or
                        {"checked": 0, "changed": 0, "missing": 0, "failed": 0})
    assert api.post("/media/remeasure-durations", json={"all": True}).status_code == 401
    r = api.post("/media/remeasure-durations", json={"all": True}, headers=AUTH)
    assert r.status_code == 202
    for _ in range(50):
        s = api.get("/media/remeasure-durations", headers=AUTH).json()
        if not s["running"]:
            break
        import time
        time.sleep(0.05)
    assert s["result"]["checked"] == 0 and seen == [False]


# ---------- migrations and backups ----------

def test_migration_adds_columns_to_old_database(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path}/old.db")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE media (id INTEGER PRIMARY KEY, filename VARCHAR)"))
        c.execute(text("CREATE TABLE playlists (id INTEGER PRIMARY KEY, name VARCHAR)"))
        c.execute(text("INSERT INTO media (id, filename) VALUES (1, 'a')"))
        c.execute(text("INSERT INTO playlists (id, name) VALUES (1, 'p')"))
    monkeypatch.setattr(main, "engine", eng)
    main._ensure_audio_rotation_columns()
    main._ensure_audio_rotation_columns()          # idempotent
    cols = {c["name"] for c in inspect(eng).get_columns("media")}
    assert {"enabled", "duration_source", "vocals"} <= cols
    with eng.connect() as c:
        assert c.execute(text("SELECT enabled FROM media")).scalar() in (1, True)
        row = c.execute(text("SELECT audio_folder, audio_shuffle, repeat_gap_tracks, "
                             "repeat_gap_minutes FROM playlists")).one()
    assert tuple(row) == (None, 0, 10, 60)


def test_backup_includes_play_history(api, tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_PATH", str(tmp_path / "backups"))
    assert "play_history" in [t.name for t in Base.metadata.sorted_tables]
    db = main.SessionLocal()
    db.add(PlayHistory(playlist_id=7, title="Kept", started_at=datetime.now(timezone.utc),
                       outcome="natural"))
    db.commit()
    db.close()
    b = backup.create_backup(main.engine, Base.metadata, str(tmp_path / "media"), include_media=False)
    with tarfile.open(tmp_path / "backups" / b["name"]) as tar:
        data = json.loads(tar.extractfile("database.json").read())
    assert [r["title"] for r in data["tables"]["play_history"]] == ["Kept"]
    db = main.SessionLocal()
    db.query(PlayHistory).delete()
    db.commit()
    db.close()
    backup.restore_backup(main.engine, Base.metadata, str(tmp_path / "media"), b["name"])
    db = main.SessionLocal()
    assert [r.title for r in db.query(PlayHistory).all()] == ["Kept"]
    db.close()


def test_restore_old_backup_without_new_tables_or_columns(api):
    """A backup from before this change: no play_history table and no new columns."""
    old = {"format": backup.FORMAT_VERSION, "tables": {
        "media": [{"id": 5, "filename": "s.mka", "original_filename": "s.mp3", "title": "Old song",
                   "filepath": "/x/s", "folder": "Music", "kind": "audio", "status": "ready",
                   "duration": 61.0}],
        "playlists": [{"id": 3, "name": "Old radio", "mode": "separate_audio"}],
        "playlist_audio": [{"playlist_id": 3, "media_id": 5, "position": 0}],
    }}
    db = main.SessionLocal()
    db.add(PlayHistory(playlist_id=1, title="current", started_at=datetime.now(timezone.utc)))
    db.commit()
    db.close()
    backup.load_database(main.engine, Base.metadata, old)
    db = main.SessionLocal()
    m = db.query(Media).one()
    assert (m.title, m.enabled, m.vocals, m.duration_source) == ("Old song", True, None, None)
    p = db.query(Playlist).one()
    assert (p.audio_folder, bool(p.audio_shuffle), p.repeat_gap_tracks, p.repeat_gap_minutes) == \
        (None, False, 10, 60)
    assert db.query(PlayHistory).count() == 0        # history replaced by the backup's (none)
    db.close()
    files = main.playlist_files_loader(3)()
    assert [x["title"] for x in files["audio_meta"]] == ["Old song"]
