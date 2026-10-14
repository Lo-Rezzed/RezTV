import json
import shutil
import subprocess
import tarfile

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine

from app.services import backup, overlay
from app.services.hls import _build_separate_audio_cmd, _video_out


def test_item_at_cycles():
    d = [5, 10, 5]
    assert [overlay.item_at(d, t) for t in (0, 4.9, 5, 14.9, 15, 20, 25)] == [0, 0, 1, 1, 2, 0, 1]
    assert overlay.item_at([None, 0], 12) == 1  # unknown durations fall back to 10 s


def test_labels():
    assert overlay.label_for_clip({"id": 74}) == "ID 74"
    assert overlay.label_for_song({"title": "Moonlit Skyline.mp3"}) == "\u266a Moonlit Skyline"
    assert overlay.label_for_song({}) == ""


def test_ticker_writes_files(tmp_path):
    t = overlay.OverlayTicker(tmp_path / "id.txt", tmp_path / "song.txt",
                              [{"id": 1, "duration": 5}, {"id": 2, "duration": 5}],
                              [{"title": "A", "duration": 100}])
    assert (tmp_path / "id.txt").read_text() == "ID 1"
    t.render(6)
    assert (tmp_path / "id.txt").read_text() == "ID 2"
    assert (tmp_path / "song.txt").read_text() == "\u266a A"


def test_overlay_only_when_enabled(tmp_path):
    assert _video_out(None)[1] == "fps=30,format=yuv420p"
    cmd = _build_separate_audio_cmd(tmp_path / "v", tmp_path / "a", tmp_path, tmp_path / "o.m3u8",
                                    overlay=(tmp_path / "i.txt", tmp_path / "s.txt"))
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.count("drawtext") == 2 and "reload=1" in vf


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_drawtext_filter_runs(tmp_path):
    (tmp_path / "i.txt").write_text("ID 74")
    (tmp_path / "s.txt").write_text("\u266a Song: A, B")
    vf = "fps=30,format=yuv420p," + overlay.drawtext_filters(tmp_path / "i.txt", tmp_path / "s.txt")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30",
                    "-t", "1", "-vf", vf, "-f", "null", "-"], check=True)


def _db(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    md = MetaData()
    t = Table("items", md, Column("id", Integer, primary_key=True), Column("name", String),
              Column("at", DateTime))
    md.create_all(eng)
    return eng, md, t


def test_backup_and_restore_roundtrip(tmp_path, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(backup, "BACKUP_PATH", str(tmp_path / "backups"))
    eng, md, t = _db(tmp_path)
    media = tmp_path / "media"
    (media / "Filler").mkdir(parents=True)
    (media / "Filler" / "a.mp4").write_bytes(b"clip")
    with eng.begin() as c:
        c.execute(t.insert(), [{"id": 1, "name": "one", "at": datetime(2026, 10, 14, 9)}])
    b = backup.create_backup(eng, md, str(media))
    with tarfile.open(tmp_path / "backups" / b["name"]) as tar:
        names = tar.getnames()
        assert "database.json" in names and "media/Filler/a.mp4" in names
        assert json.loads(tar.extractfile("database.json").read())["tables"]["items"][0]["name"] == "one"
    # change everything, then restore
    with eng.begin() as c:
        c.execute(t.delete())
        c.execute(t.insert(), [{"id": 2, "name": "two"}])
    (media / "Filler" / "a.mp4").write_bytes(b"changed")
    r = backup.restore_backup(eng, md, str(media), b["name"])
    assert r["media_files"] == 1
    with eng.connect() as c:
        rows = c.execute(t.select()).all()
    assert [(x.id, x.name) for x in rows] == [(1, "one")] and rows[0].at == datetime(2026, 10, 14, 9)
    assert (media / "Filler" / "a.mp4").read_bytes() == b"clip"


def test_resolve_rejects_bad_names(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_PATH", str(tmp_path))
    for bad in ("../etc/passwd", "x.tar.gz", "reztv-backup-20261014-090000.tar.gz/../a"):
        with pytest.raises((ValueError, FileNotFoundError)):
            backup.resolve(bad)


def test_scheduler_and_prune(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_PATH", str(tmp_path / "b"))
    eng, md, _ = _db(tmp_path)
    cfg = {"interval_hours": 1, "keep": 2, "include_media": False}
    calls = []

    def run(c):
        calls.append(1)
        backup.create_backup(eng, md, str(tmp_path), include_media=False, label="auto")
    s = backup.Scheduler(lambda: cfg, run)
    assert s.tick() is True        # nothing yet, runs
    assert s.tick() is False       # just ran
    import time
    for _ in range(3):
        s.tick(now=time.time() + 7200)
    assert len([b for b in backup.list_backups() if b["scheduled"]]) == 2  # pruned to keep
    cfg["interval_hours"] = 0
    assert s.tick(now=time.time() + 99999) is False
