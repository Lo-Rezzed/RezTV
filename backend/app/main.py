from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text, func
from pydantic import BaseModel, Field, field_validator
import subprocess
import time
import threading
from collections import defaultdict, deque
from fastapi import Request
from typing import List
import os
import uuid
import re

import logging
from contextlib import asynccontextmanager
from app.services.hls import (start_playlist_stream, stop_playlist_stream, stop_all,
                              stream_status, read_log_tail)
from app.core.database import SessionLocal

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("reztv")
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.core.database import engine, Base, get_db
from app.models.media import Media
from app.models.playlist import Playlist
from app.models.playlist import playlist_media
from app.models.settings import Settings
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi import status
import secrets

Base.metadata.create_all(bind=engine)

# Lightweight migration: older databases were created before media folders existed.
# Add the column in place so existing media keeps working (it lands in "Unsorted").
def _ensure_media_folder_column():
    columns = [c["name"] for c in inspect(engine).get_columns("media")]
    if "folder" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE media ADD COLUMN folder VARCHAR NOT NULL DEFAULT 'Unsorted'"))

_ensure_media_folder_column()

def _ensure_playlist_running_column():
    columns = [c["name"] for c in inspect(engine).get_columns("playlists")]
    if "stream_running" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE playlists ADD COLUMN stream_running BOOLEAN NOT NULL DEFAULT false"))

_ensure_playlist_running_column()


def playlist_files_loader(playlist_id: int):
    """Returns a function that reads the channel's current files from the DB.
    The stream supervisor calls it on every (re)start, with a fresh session."""
    def load() -> list[str]:
        db = SessionLocal()
        try:
            p = db.query(Playlist).filter(Playlist.id == playlist_id).first()
            return [m.filepath for m in p.media_items] if p else []
        finally:
            db.close()
    return load


def resume_streams():
    db = SessionLocal()
    try:
        ids = [p.id for p in db.query(Playlist).filter(Playlist.stream_running.is_(True)).all()]
    finally:
        db.close()
    for pid in ids:
        try:
            start_playlist_stream(pid, playlist_files_loader(pid))
            log.info("Resumed channel %s after startup", pid)
        except ValueError as e:
            log.warning("Channel %s marked running but could not resume: %s", pid, e)


@asynccontextmanager
async def lifespan(app):
    resume_streams()
    yield
    stop_all()  # stream_running flags stay set, so channels come back on next start

DEFAULT_FOLDER = "Unsorted"

def clean_folder_name(name: str | None) -> str:
    """Folder names are also used as directory names, so keep them simple and safe."""
    name = (name or "").strip()
    name = re.sub(r"[^A-Za-z0-9 _-]", "", name)
    name = re.sub(r"\s+", " ", name).strip()[:64]
    return name or DEFAULT_FOLDER

app = FastAPI(title="RezTV", version="0.1.0", lifespan=lifespan)
security = HTTPBasic()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD is not set. Put it in your .env file before starting RezTV.")

# Simple login rate limiting: too many failed logins from one IP locks it out for a while.
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "900"))
_failed_logins: dict[str, deque] = defaultdict(deque)
_failed_lock = threading.Lock()

def _client_ip(request: Request) -> str:
    # Behind nginx the real address arrives in X-Real-IP / X-Forwarded-For.
    # Port 8000 is bound to 127.0.0.1 so only nginx can set these.
    fwd = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return fwd or (request.client.host if request.client else "unknown")

def verify_admin(request: Request, credentials: HTTPBasicCredentials = Depends(security)):
    ip = _client_ip(request)
    now = time.monotonic()
    with _failed_lock:
        q = _failed_logins[ip]
        while q and now - q[0] > LOGIN_WINDOW_SECONDS:
            q.popleft()
        if len(q) >= LOGIN_MAX_FAILURES:
            raise HTTPException(status_code=429, detail="Too many failed logins. Try again later.",
                                headers={"Retry-After": str(int(LOGIN_WINDOW_SECONDS - (now - q[0])) + 1)})
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (correct_username and correct_password):
        with _failed_lock:
            _failed_logins[ip].append(now)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    with _failed_lock:
        _failed_logins.pop(ip, None)
    return credentials.username

app.mount("/static", StaticFiles(directory="app/static"), name="static")

MEDIA_PATH = os.getenv("MEDIA_PATH", "/app/media")
HLS_PATH = os.getenv("HLS_PATH", "/app/hls")

app.mount("/hls", StaticFiles(directory=HLS_PATH), name="hls")

os.makedirs(MEDIA_PATH, exist_ok=True)
os.makedirs(HLS_PATH, exist_ok=True)

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "2048")) * 1024 * 1024
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
CHUNK_SIZE = 1024 * 1024

def _clean_text(v: str) -> str:
    v = re.sub(r"[\x00-\x1f\x7f]", "", v).strip()
    if not v:
        raise ValueError("must not be empty")
    return v

class PlaylistCreate(BaseModel):
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=500)
    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return _clean_text(v)
class PlaylistUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    @field_validator("name")
    @classmethod
    def _name(cls, v):
        return None if v is None else _clean_text(v)
class SettingsUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    station_name: str | None = Field(default=None, max_length=100)
    @field_validator("station_name")
    @classmethod
    def _sn(cls, v):
        return None if v is None else _clean_text(v)

def media_public(m: Media) -> dict:
    # Never expose server file paths or stored filenames.
    return {"id": m.id, "title": m.title or m.original_filename,
            "original_filename": m.original_filename, "folder": m.folder,
            "duration": m.duration, "created_at": m.created_at}

def playlist_public(p: Playlist) -> dict:
    return {"id": p.id, "name": p.name, "description": p.description, "created_at": p.created_at}

def probe_video(path: str) -> float | None:
    """Return duration if ffprobe finds a video stream, else raise ValueError."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=codec_type:format=duration",
                            "-of", "default=noprint_wrappers=1", path],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ValueError(f"could not check file: {e}")
    if r.returncode != 0 or "codec_type=video" not in r.stdout:
        raise ValueError("not a readable video file")
    m = re.search(r"duration=([0-9.]+)", r.stdout)
    return float(m.group(1)) if m else None
class ReorderRequest(BaseModel):
    media_ids: List[int]
class MediaUpdate(BaseModel):
    folder: str | None = None
    title: str | None = None
class FolderRequest(BaseModel):
    folder: str

def next_position(db: Session, playlist_id: int) -> int:
    current = db.query(func.max(playlist_media.c.position)).filter(
        playlist_media.c.playlist_id == playlist_id
    ).scalar()
    return 0 if current is None else current + 1

def append_to_playlist(db: Session, playlist_id: int, media_id: int) -> bool:
    """Add media to the end of a playlist. Returns False if it was already there."""
    exists = db.execute(
        playlist_media.select().where(
            (playlist_media.c.playlist_id == playlist_id) & (playlist_media.c.media_id == media_id)
        )
    ).first()
    if exists:
        return False
    db.execute(
        playlist_media.insert().values(
            playlist_id=playlist_id,
            media_id=media_id,
            position=next_position(db, playlist_id)
        )
    )
    return True

@app.get("/")
async def root():
    return FileResponse("app/static/landing.html")

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/admin")
async def admin_page(username: str = Depends(verify_admin)):
    return FileResponse("app/static/index.html")

@app.post("/upload")
async def upload_video(
    file: UploadFile = File(...),
    folder: str = Form(""),
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only MP4, MOV, MKV and WebM files are allowed")
    unique_name = f"{uuid.uuid4()}{ext}"
    folder_name = clean_folder_name(folder)
    folder_dir = os.path.join(MEDIA_PATH, folder_name)
    os.makedirs(folder_dir, exist_ok=True)
    file_location = os.path.join(folder_dir, unique_name)

    written = 0
    try:
        with open(file_location, "wb") as buffer:
            while chunk := await file.read(CHUNK_SIZE):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"File is larger than {MAX_UPLOAD_BYTES // (1024*1024)} MB")
                buffer.write(chunk)
        duration = probe_video(file_location)
    except ValueError as e:
        os.remove(file_location)
        raise HTTPException(status_code=400, detail=f"Rejected: {e}")
    except BaseException:
        if os.path.exists(file_location):
            os.remove(file_location)
        raise

    media = Media(
        filename=unique_name,
        original_filename=file.filename,
        title=file.filename,
        filepath=file_location,
        folder=folder_name,
        duration=duration
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    return {
        "id": media.id,
        "filename": media.original_filename,
        "folder": media.folder,
        "status": "uploaded"
    }

@app.get("/media")
async def list_media(folder: str | None = None, db: Session = Depends(get_db),
                     username: str = Depends(verify_admin)):
    query = db.query(Media)
    if folder:
        query = query.filter(Media.folder == clean_folder_name(folder))
    return [media_public(m) for m in query.order_by(Media.id).all()]

@app.get("/media/folders")
async def list_folders(db: Session = Depends(get_db), username: str = Depends(verify_admin)):
    rows = db.query(Media.folder, func.count(Media.id)).group_by(Media.folder).order_by(Media.folder).all()
    return [{"name": name, "count": count} for name, count in rows]

@app.put("/media/{media_id}")
async def update_media(
    media_id: int,
    data: MediaUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    # Moving only changes the folder label. The file stays where it is on disk,
    # so channels that are streaming it keep working.
    media = db.query(Media).filter(Media.id == media_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    if data.folder is not None:
        media.folder = clean_folder_name(data.folder)
    if data.title is not None and data.title.strip():
        media.title = data.title.strip()
    db.commit()
    db.refresh(media)
    return media_public(media)

@app.post("/playlists")
async def create_playlist(
    playlist: PlaylistCreate,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    db_playlist = Playlist(name=playlist.name, description=playlist.description)
    db.add(db_playlist)
    db.commit()
    db.refresh(db_playlist)
    return playlist_public(db_playlist)

@app.get("/playlists")
async def list_playlists(db: Session = Depends(get_db)):
    return [playlist_public(p) for p in db.query(Playlist).order_by(Playlist.id).all()]
@app.post("/playlists/{playlist_id}/media/{media_id}")
async def add_media_to_playlist(
    playlist_id: int,
    media_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    media = db.query(Media).filter(Media.id == media_id).first()

    if not playlist or not media:
        raise HTTPException(status_code=404, detail="Playlist or Media not found")

    append_to_playlist(db, playlist_id, media_id)
    db.commit()

    return {"status": "added", "playlist_id": playlist_id, "media_id": media_id}

@app.delete("/playlists/{playlist_id}/media/{media_id}")
async def remove_media_from_playlist(
    playlist_id: int,
    media_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    # Takes the video off this channel only. The file stays in the media library.
    result = db.execute(
        playlist_media.delete().where(
            (playlist_media.c.playlist_id == playlist_id) & (playlist_media.c.media_id == media_id)
        )
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="That video is not in this channel")
    return {"status": "removed", "playlist_id": playlist_id, "media_id": media_id}

@app.post("/playlists/{playlist_id}/folder")
async def add_folder_to_playlist(
    playlist_id: int,
    data: FolderRequest,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    folder_name = clean_folder_name(data.folder)
    media_items = db.query(Media).filter(Media.folder == folder_name).order_by(Media.id).all()
    if not media_items:
        raise HTTPException(status_code=404, detail="Folder is empty or does not exist")
    added = [m.id for m in media_items if append_to_playlist(db, playlist_id, m.id)]
    db.commit()
    return {"status": "added", "playlist_id": playlist_id, "folder": folder_name, "added": added,
            "skipped": len(media_items) - len(added)}

@app.get("/playlists/{playlist_id}")
async def get_playlist(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return playlist_public(playlist)

@app.get("/channel/{channel_id}")
async def channel_page(channel_id: int):
    return FileResponse("app/static/player.html")

@app.post("/playlists/{playlist_id}/start")
async def start_stream(
    playlist_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    if not playlist.media_items:
        raise HTTPException(status_code=400, detail="Playlist has no media")

    try:
        start_playlist_stream(playlist_id, playlist_files_loader(playlist_id))
        playlist.stream_running = True
        db.commit()
        return {
            "status": "started",
            "playlist_id": playlist_id,
            "stream_url": f"/hls/playlist_{playlist_id}/index.m3u8"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        log.exception("Could not start channel %s", playlist_id)
        raise HTTPException(status_code=500, detail=f"Could not start stream: {e}")

@app.post("/playlists/{playlist_id}/stop")
async def stop_stream(
    playlist_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    stop_playlist_stream(playlist_id)
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if playlist:
        playlist.stream_running = False
        db.commit()
    return {"status": "stopped", "playlist_id": playlist_id}


@app.get("/playlists/{playlist_id}/status")
async def get_stream_status(playlist_id: int, lines: int = 50,
                            db: Session = Depends(get_db),
                            username: str = Depends(verify_admin)):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    lines = max(1, min(lines, 500))
    return {"playlist_id": playlist_id, "should_run": bool(playlist.stream_running),
            **stream_status(playlist_id), "log": read_log_tail(playlist_id, lines)}

@app.delete("/media/{media_id}")
async def delete_media(
    media_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    media = db.query(Media).filter(Media.id == media_id).first()
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    # Delete the actual file
    try:
        if os.path.exists(media.filepath):
            os.remove(media.filepath)
    except OSError as e:
        log.warning("Error deleting file %s: %s", media.filepath, e)

    db.execute(playlist_media.delete().where(playlist_media.c.media_id == media_id))
    db.delete(media)
    db.commit()
    return {"status": "deleted", "media_id": media_id}


@app.delete("/playlists/{playlist_id}")
async def delete_playlist(
    playlist_id: int,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    # Stop the stream if it's running
    stop_playlist_stream(playlist_id)

    db.delete(playlist)
    db.commit()
    return {"status": "deleted", "playlist_id": playlist_id}
@app.get("/playlists/{playlist_id}/media")
async def get_playlist_media(playlist_id: int, db: Session = Depends(get_db),
                             username: str = Depends(verify_admin)):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    
    return [
        {
            "id": m.id,
            "title": m.title or m.original_filename,
            "original_filename": m.original_filename,
            "folder": m.folder
        }
        for m in playlist.media_items
    ]


@app.post("/playlists/{playlist_id}/reorder")
async def reorder_playlist(
    playlist_id: int,
    data: ReorderRequest,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")

    # Only reorder what is already on the channel; never add or drop items here.
    current = {r[0] for r in db.execute(
        playlist_media.select().with_only_columns(playlist_media.c.media_id)
        .where(playlist_media.c.playlist_id == playlist_id))}
    if len(data.media_ids) != len(set(data.media_ids)) or set(data.media_ids) != current:
        raise HTTPException(status_code=400,
                            detail="Reorder list must contain exactly the channel's current videos")

    # One transaction: delete + re-insert succeed together or not at all.
    try:
        db.execute(playlist_media.delete().where(playlist_media.c.playlist_id == playlist_id))
        db.execute(playlist_media.insert(), [
            {"playlist_id": playlist_id, "media_id": mid, "position": pos}
            for pos, mid in enumerate(data.media_ids)])
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Reorder failed for channel %s; rolled back", playlist_id)
        raise HTTPException(status_code=500, detail="Reorder failed; order unchanged")
    return {"status": "reordered", "playlist_id": playlist_id}
@app.get("/settings")
async def get_settings(db: Session = Depends(get_db)):
    settings = db.query(Settings).first()
    if not settings:
        settings = Settings(station_name="RezTV")
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return {"station_name": settings.station_name}


@app.post("/settings")
async def update_settings(
    data: SettingsUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    settings = db.query(Settings).first()
    if not settings:
        settings = Settings()
        db.add(settings)
    
    if data.station_name is not None:
        settings.station_name = data.station_name
    
    db.commit()
    return {"station_name": settings.station_name}


@app.put("/playlists/{playlist_id}")
async def rename_playlist(
    playlist_id: int,
    data: PlaylistUpdate,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    if data.name is not None:
        playlist.name = data.name
    if data.description is not None:
        playlist.description = data.description.strip() or None
    db.commit()
    db.refresh(playlist)
    return playlist_public(playlist)
