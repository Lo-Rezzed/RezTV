"""Admin API: media search/sort, folders, duplicate check, upload report, backup download.
Runs the real app against a throwaway SQLite database (no lifespan, so no converter
thread or streams start)."""
import base64
import os
import shutil
import subprocess
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="reztv-test-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP}/test.db")
os.environ.setdefault("ADMIN_PASSWORD", "test-password")
os.environ.setdefault("MEDIA_PATH", f"{_TMP}/media")
os.environ.setdefault("HLS_PATH", f"{_TMP}/hls")
os.environ.setdefault("LOG_PATH", f"{_TMP}/logs")
os.environ.setdefault("BACKUP_PATH", f"{_TMP}/backups")

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.models.media import Media  # noqa: E402
from app.services import backup  # noqa: E402

AUTH = {"Authorization": "Basic " + base64.b64encode(
    f"{main.ADMIN_USERNAME}:{main.ADMIN_PASSWORD}".encode()).decode()}
BAD_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:wrong").decode()}


@pytest.fixture
def client(monkeypatch, tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(main, "MEDIA_PATH", str(media))
    monkeypatch.setattr(backup, "BACKUP_PATH", str(tmp_path / "backups"))
    monkeypatch.setattr(main.converter, "enqueue", lambda mid: None)
    main._failed_logins.clear()
    db = main.SessionLocal()
    db.query(Media).delete()
    db.commit()
    db.close()
    yield TestClient(main.app)
    main._failed_logins.clear()


def add_media(names, folder="Filler"):
    db = main.SessionLocal()
    ids = []
    for n in names:
        m = Media(filename=f"{n}.mp4", original_filename=n, title=n, filepath=f"/x/{n}",
                  folder=folder, kind="video", status="ready")
        db.add(m)
        db.commit()
        ids.append(m.id)
    db.close()
    return ids


# ---------- search and sort ----------

def test_search_and_sort(client):
    ids = add_media(["lm_b17_01.mp4", "lm_b17_02.mp4", "dcw7_01.mp4"])
    add_media(["LM_B17_03.mp4"], folder="Programs")
    r = client.get("/media", params={"page": 1, "q": "b17", "sort": "newest"}, headers=AUTH).json()
    assert [m["original_filename"] for m in r["items"]] == ["LM_B17_03.mp4", "lm_b17_02.mp4", "lm_b17_01.mp4"]
    assert r["total"] == 3
    r = client.get("/media", params={"page": 1, "q": "b17", "folder": "Filler"}, headers=AUTH).json()
    assert [m["id"] for m in r["items"]] == ids[:2]  # oldest first by default, folder only
    # LIKE wildcards are matched literally
    assert client.get("/media", params={"page": 1, "q": "%"}, headers=AUTH).json()["total"] == 0
    assert client.get("/media", params={"page": 1, "q": "b17_0"}, headers=AUTH).json()["total"] == 3
    assert client.get("/media", params={"sort": "sideways"}, headers=AUTH).status_code == 400


def test_page_size(client):
    add_media([f"clip_{i:03d}.mp4" for i in range(60)])
    r = client.get("/media", params={"page": 2, "page_size": 50, "sort": "newest"}, headers=AUTH).json()
    assert r["pages"] == 2 and len(r["items"]) == 10 and r["items"][0]["original_filename"] == "clip_009.mp4"


# ---------- folders ----------

def test_create_folder_shows_up_empty(client):
    r = client.post("/media/folders", json={"folder": "Archillite-Filler"}, headers=AUTH)
    assert r.status_code == 200 and r.json() == {"name": "Archillite-Filler", "created": True}
    assert client.post("/media/folders", json={"folder": "Archillite-Filler"},
                       headers=AUTH).json()["created"] is False
    add_media(["a.mp4"], folder="Programs")
    folders = client.get("/media/folders", headers=AUTH).json()
    assert {"name": "Archillite-Filler", "count": 0, "converting": 0} in folders
    assert any(f["name"] == "Programs" and f["count"] == 1 for f in folders)


@pytest.mark.parametrize("bad", ["", "   ", "../etc", "Filler/Sub", "bad*name", "x" * 65])
def test_create_folder_rejects_unsafe_names(client, bad):
    assert client.post("/media/folders", json={"folder": bad}, headers=AUTH).status_code == 400
    assert not any(n not in ("Unsorted",) for n in os.listdir(main.MEDIA_PATH))


def test_create_folder_needs_auth(client):
    assert client.post("/media/folders", json={"folder": "X"}).status_code == 401


# ---------- duplicate check ----------

def test_duplicate_check(client):
    ids = add_media(["lm_b18_01.mp4", "lm_b18_01.mp4", "lm_b18_02.mp4"])
    add_media(["other.mp4"], folder="Programs")
    r = client.post("/media/duplicates", headers=AUTH, json={
        "folder": "Filler", "filenames": ["LM_B18_01.mp4", "lm_b18_02.mp4", "new.mp4", "other.mp4"]}).json()
    assert r["folder"] == "Filler"
    assert r["duplicates"] == [{"filename": "LM_B18_01.mp4", "ids": ids[:2]},
                               {"filename": "lm_b18_02.mp4", "ids": [ids[2]]}]
    # same names in another folder are not duplicates
    r = client.post("/media/duplicates", headers=AUTH,
                    json={"folder": "Programs", "filenames": ["lm_b18_01.mp4"]}).json()
    assert r["duplicates"] == []
    assert client.post("/media/duplicates", json={"folder": "Filler", "filenames": []}).status_code == 401


# ---------- upload report ----------

@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
@pytest.mark.parametrize("rate,converted", [("30", False), ("30000/1001", True)])
def test_upload_reports_conform_decision(client, tmp_path, rate, converted):
    src = tmp_path / "clip.mp4"
    from app.services import convert
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"testsrc=size={convert.WIDTH}x{convert.HEIGHT}:rate={rate}",
                    "-f", "lavfi", "-i", "sine=sample_rate=44100", "-ac", "2", "-c:a", "aac",
                    "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
    with open(src, "rb") as f:
        r = client.post("/upload", headers=AUTH, data={"folder": "Filler"},
                        files={"file": ("clip.mp4", f, "video/mp4")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["folder"] == "Filler" and d["conform"]["converted"] is converted
    assert d["conform"]["action"] == ("reencode" if converted else "remux")


# ---------- backup download ----------

def _backup_file(name="reztv-backup-20261025-120000.tar.gz", data=b"x" * 3_000_000):
    d = backup.backup_dir()
    (d / name).write_bytes(data)
    return name, data


def test_download_backup_streams_file(client):
    name, data = _backup_file()
    r = client.get(f"/backups/{name}/download", headers=AUTH)
    assert r.status_code == 200 and r.content == data
    assert r.headers["content-type"] == "application/gzip"
    assert name in r.headers["content-disposition"]
    assert r.headers["content-length"] == str(len(data))


def test_download_backup_needs_auth(client):
    name, _ = _backup_file()
    assert client.get(f"/backups/{name}/download").status_code == 401
    assert client.get(f"/backups/{name}/download", headers=BAD_AUTH).status_code == 401


@pytest.mark.parametrize("bad", ["..%2F..%2Fetc%2Fpasswd", "secret.txt", "reztv-backup-1.tar.gz",
                                 "reztv-backup-20261025-120000.tar.gz.partial",
                                 "reztv-backup-20261025-999999.tar.gz"])
def test_download_backup_path_safety(client, tmp_path, bad):
    _backup_file()
    (backup.backup_dir() / "secret.txt").write_text("nope")
    (backup.backup_dir() / "reztv-backup-20261025-120000.tar.gz.partial").write_text("nope")
    (tmp_path / "outside.tar.gz").write_text("nope")
    r = client.get(f"/backups/{bad}/download", headers=AUTH)
    assert r.status_code == 404
