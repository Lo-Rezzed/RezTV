"""Station backups: one .tar.gz holding a JSON dump of every database table
(database.json) and, optionally, the media folder (media/...).

The dump goes through SQLAlchemy, so it needs no pg_dump in the container and
works the same on PostgreSQL and SQLite. Restore replaces every table's rows and
the media files with the backup's copy."""
import io
import json
import logging
import os
import re
import tarfile
import threading
import time
import uuid
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import DateTime, text

log = logging.getLogger("reztv.backup")

BACKUP_PATH = os.getenv("BACKUP_PATH", "/app/backups")
FORMAT_VERSION = 1
NAME_RE = re.compile(r"^reztv-backup-\d{8}-\d{6}(-[a-z0-9-]+)?\.tar\.gz$")
_lock = threading.Lock()  # one backup or restore at a time


def backup_dir() -> Path:
    p = Path(BACKUP_PATH)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _tables(metadata):
    return list(metadata.sorted_tables)  # parents before children


def _jsonable(v):
    return v.isoformat() if isinstance(v, (datetime, date)) else v


def dump_database(engine, metadata) -> dict:
    out = {"format": FORMAT_VERSION, "created": datetime.now().isoformat(), "tables": {}}
    with engine.connect() as conn:
        for t in _tables(metadata):
            rows = conn.execute(t.select()).mappings().all()
            out["tables"][t.name] = [{k: _jsonable(v) for k, v in r.items()} for r in rows]
    return out


def load_database(engine, metadata, data: dict):
    if data.get("format") != FORMAT_VERSION:
        raise ValueError("Unknown backup format")
    tables = _tables(metadata)
    with engine.begin() as conn:  # all or nothing
        for t in reversed(tables):
            conn.execute(t.delete())
        for t in tables:
            rows = data["tables"].get(t.name) or []
            cols = {c.name: c for c in t.columns}
            clean = []
            for r in rows:
                row = {}
                for k, v in r.items():
                    if k not in cols:
                        continue  # column from a newer/older version; skip
                    if v is not None and isinstance(cols[k].type, DateTime) and isinstance(v, str):
                        v = datetime.fromisoformat(v)
                    row[k] = v
                clean.append(row)
            if clean:
                conn.execute(t.insert(), clean)
        if engine.dialect.name == "postgresql":
            # Keep id sequences ahead of the restored ids.
            for t in tables:
                if "id" in t.columns and t.columns["id"].primary_key:
                    conn.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{t.name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {t.name}), 0) + 1, false)"))


def _media_totals(media_path: str) -> tuple[int, int]:
    files = size = 0
    for root, _dirs, names in os.walk(media_path):
        for n in names:
            try:
                size += os.path.getsize(os.path.join(root, n))
                files += 1
            except OSError:
                pass
    return files, size


def create_backup(engine, metadata, media_path: str, include_media: bool = True,
                  label: str = "", progress=None) -> dict:
    """`progress`, if given, is called as progress(files_done, files_total,
    bytes_done, bytes_total) while media files are added."""
    with _lock:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        suffix = f"-{label}" if label else ""
        final = backup_dir() / f"reztv-backup-{stamp}{suffix}.tar.gz"
        n = 1
        while final.exists():
            final = backup_dir() / f"reztv-backup-{stamp}{suffix}-{n}.tar.gz"
            n += 1
        tmp = final.with_name(final.name + ".partial")
        payload = json.dumps(dump_database(engine, metadata), indent=1).encode()
        try:
            with tarfile.open(tmp, "w:gz", compresslevel=1) as tar:
                info = tarfile.TarInfo("database.json")
                info.size, info.mtime = len(payload), int(time.time())
                tar.addfile(info, io.BytesIO(payload))
                if include_media and os.path.isdir(media_path):
                    if progress is None:
                        tar.add(media_path, arcname="media")
                    else:
                        files_total, bytes_total = _media_totals(media_path)
                        done = {"files": 0, "bytes": 0}

                        def count(ti):
                            if ti.isfile():
                                done["files"] += 1
                                done["bytes"] += ti.size
                                progress(done["files"], files_total, done["bytes"], bytes_total)
                            return ti
                        progress(0, files_total, 0, bytes_total)
                        tar.add(media_path, arcname="media", filter=count)
            os.replace(tmp, final)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        log.info("Backup written: %s", final.name)
        return describe(final)


class BusyError(RuntimeError):
    """A backup or restore is already running."""


def busy() -> bool:
    return _lock.locked() or (_job is not None and _job["state"] == "running")


# Manual "Back up now" runs in the background so the request returns at once
# (a backup with media can take longer than nginx's proxy_read_timeout).
# Only the latest job is remembered; it lives in memory until the next one.
_job: dict | None = None
_job_lock = threading.Lock()


def current_job() -> dict | None:
    with _job_lock:
        return dict(_job) if _job else None


def start_backup_job(engine, metadata, media_path: str, include_media: bool = True,
                     label: str = "") -> dict:
    """Start a backup in a background thread and return its job record.
    Raises BusyError if a backup or restore is already running."""
    global _job
    with _job_lock:
        if busy():
            raise BusyError("A backup or restore is already running")
        job = {"id": uuid.uuid4().hex, "state": "running", "include_media": include_media,
               "started": datetime.now().isoformat(timespec="seconds"), "finished": None,
               "files_done": 0, "files_total": None, "bytes_done": 0, "bytes_total": None,
               "name": None, "size": None, "error": None}
        _job = job

    def update(**fields):
        with _job_lock:
            job.update(fields)

    def progress(files_done, files_total, bytes_done, bytes_total):
        update(files_done=files_done, files_total=files_total,
               bytes_done=bytes_done, bytes_total=bytes_total)

    def run():
        try:
            result = create_backup(engine, metadata, media_path, include_media=include_media,
                                   label=label, progress=progress)
            update(state="done", name=result["name"], size=result["size"])
        except Exception as e:  # reported to the admin page via the job record
            log.exception("Background backup failed")
            update(state="error", error=str(e) or e.__class__.__name__)
        finally:
            update(finished=datetime.now().isoformat(timespec="seconds"))

    threading.Thread(target=run, daemon=True, name=f"backup-{job['id'][:8]}").start()
    return current_job()


def describe(path: Path) -> dict:
    st = path.stat()
    return {"name": path.name, "size": st.st_size,
            "created": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "scheduled": "-auto" in path.name, "pre_restore": "-pre-restore" in path.name}


def list_backups() -> list[dict]:
    return [describe(p) for p in sorted(backup_dir().glob("reztv-backup-*.tar.gz"),
                                        key=lambda p: p.stat().st_mtime, reverse=True)]


def resolve(name: str) -> Path:
    if not NAME_RE.match(name or ""):
        raise ValueError("Not a backup name")
    p = backup_dir() / name
    if not p.is_file():
        raise FileNotFoundError(name)
    return p


def prune(keep: int, only_scheduled: bool = True):
    """Keep the newest `keep` scheduled backups (manual ones are never pruned)."""
    items = [b for b in list_backups() if b["scheduled"] or not only_scheduled]
    for b in items[max(keep, 1):]:
        try:
            (backup_dir() / b["name"]).unlink()
            log.info("Pruned old backup %s", b["name"])
        except OSError as e:
            log.warning("Could not prune %s: %s", b["name"], e)


def restore_backup(engine, metadata, media_path: str, name: str) -> dict:
    path = resolve(name)
    with _lock:
        with tarfile.open(path, "r:gz") as tar:
            member = tar.getmember("database.json")
            data = json.loads(tar.extractfile(member).read())
            media_members = [m for m in tar.getmembers()
                             if m.name == "media" or m.name.startswith("media/")]
            load_database(engine, metadata, data)
            restored_files = 0
            if media_members:
                # Extract into the parent of media_path under the name "media",
                # then the files land exactly where the restored DB rows point.
                root = Path(media_path)
                for m in media_members:
                    rel = m.name[len("media"):].lstrip("/")
                    if not (m.isfile() or m.isdir()):
                        continue  # no links or devices
                    target = (root / rel).resolve()
                    if root.resolve() not in (target, *target.parents):
                        continue  # path escapes the media folder
                    if m.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    src = tar.extractfile(m)
                    tmp = target.with_name(target.name + ".restoring")
                    with open(tmp, "wb") as f:
                        while chunk := src.read(1024 * 1024):
                            f.write(chunk)
                    os.replace(tmp, target)
                    restored_files += 1
    log.info("Restored backup %s (%d media files)", name, restored_files)
    return {"restored": name, "media_files": restored_files,
            "media_included": bool(media_members)}


class Scheduler:
    """Runs a backup every `interval_hours` (read from settings each check; 0 = off)."""

    def __init__(self, get_config, run_backup, check_seconds: float = 60):
        self.get_config, self.run_backup = get_config, run_backup
        self.check_seconds = check_seconds
        self._stop = threading.Event()
        self.last_error: str | None = None

    def _last_scheduled_time(self) -> float:
        times = [(backup_dir() / b["name"]).stat().st_mtime for b in list_backups() if b["scheduled"]]
        return max(times) if times else 0.0

    def tick(self, now: float | None = None) -> bool:
        cfg = self.get_config()
        hours = cfg.get("interval_hours") or 0
        if hours <= 0:
            return False
        now = now or time.time()
        if now - self._last_scheduled_time() < hours * 3600:
            return False
        try:
            self.run_backup(cfg)
            prune(cfg.get("keep") or 7)
            self.last_error = None
        except Exception as e:  # keep the scheduler alive
            self.last_error = str(e)
            log.exception("Scheduled backup failed")
        return True

    def start(self):
        def run():
            while not self._stop.wait(self.check_seconds):
                try:
                    self.tick()
                except Exception:
                    log.exception("Backup scheduler check failed")
        threading.Thread(target=run, daemon=True, name="backup-scheduler").start()

    def stop(self):
        self._stop.set()
