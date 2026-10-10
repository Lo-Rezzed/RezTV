from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
import os
import shutil
import uuid

from app.services.hls import start_playlist_stream, stop_playlist_stream
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

app = FastAPI(title="RezTV", version="0.1.0")
security = HTTPBasic()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

app.mount("/static", StaticFiles(directory="app/static"), name="static")

MEDIA_PATH = os.getenv("MEDIA_PATH", "/app/media")
HLS_PATH = os.getenv("HLS_PATH", "/app/hls")

app.mount("/hls", StaticFiles(directory=HLS_PATH), name="hls")

os.makedirs(MEDIA_PATH, exist_ok=True)
os.makedirs(HLS_PATH, exist_ok=True)

class PlaylistCreate(BaseModel):
    name: str
    description: str | None = None
class ReorderRequest(BaseModel):
    media_ids: List[int]

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
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    ext = os.path.splitext(file.filename)[1]
    unique_name = f"{uuid.uuid4()}{ext}"
    file_location = os.path.join(MEDIA_PATH, unique_name)

    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    media = Media(
        filename=unique_name,
        original_filename=file.filename,
        title=file.filename,
        filepath=file_location
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    return {
        "id": media.id,
        "filename": media.original_filename,
        "status": "uploaded"
    }

@app.get("/media")
async def list_media(db: Session = Depends(get_db)):
    return db.query(Media).all()

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
    return db_playlist

@app.get("/playlists")
async def list_playlists(db: Session = Depends(get_db)):
    return db.query(Playlist).all()
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

    if media not in playlist.media_items:
        playlist.media_items.append(media)
        db.commit()

    return {"status": "added", "playlist_id": playlist_id, "media_id": media_id}

@app.get("/playlists/{playlist_id}")
async def get_playlist(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return playlist

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

    media_files = [m.filepath for m in playlist.media_items]

    try:
        m3u8_path = start_playlist_stream(playlist_id, media_files)
        return {
            "status": "started",
            "playlist_id": playlist_id,
            "stream_url": f"/hls/playlist_{playlist_id}/index.m3u8"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/playlists/{playlist_id}/stop")
async def stop_stream(
    playlist_id: int,
    username: str = Depends(verify_admin)
):
    stop_playlist_stream(playlist_id)
    return {"status": "stopped", "playlist_id": playlist_id}

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
    except Exception as e:
        print(f"Error deleting file: {e}")

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
async def get_playlist_media(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Playlist not found")
    
    return [
        {
            "id": m.id,
            "title": m.title or m.original_filename,
            "original_filename": m.original_filename
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

    # Clear existing associations
    db.execute(
        playlist_media.delete().where(playlist_media.c.playlist_id == playlist_id)
    )
    db.commit()

    # Insert them again with correct position
    for position, media_id in enumerate(data.media_ids):
        db.execute(
            playlist_media.insert().values(
                playlist_id=playlist_id,
                media_id=media_id,
                position=position
            )
        )

    db.commit()
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
    data: dict,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    settings = db.query(Settings).first()
    if not settings:
        settings = Settings()
        db.add(settings)
    
    if "station_name" in data:
        settings.station_name = data["station_name"]
    
    db.commit()
    return {"station_name": settings.station_name}


@app.put("/playlists/{playlist_id}")
async def rename_playlist(
    playlist_id: int,
    data: dict,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin)
):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id).first()
    if not playlist:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    if "name" in data:
        playlist.name = data["name"]
        db.commit()
    
    return playlist
