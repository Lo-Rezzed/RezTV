from sqlalchemy import Column, Integer, String, DateTime, Boolean, Table, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

playlist_media = Table(
    "playlist_media",
    Base.metadata,
    Column("playlist_id", Integer, ForeignKey("playlists.id"), primary_key=True),
    Column("media_id", Integer, ForeignKey("media.id"), primary_key=True),
    Column("position", Integer)
)

# Music for channels in "separate_audio" mode. Kept apart from playlist_media so the
# video list and the audio list each have their own order and loop independently.
playlist_audio = Table(
    "playlist_audio",
    Base.metadata,
    Column("playlist_id", Integer, ForeignKey("playlists.id"), primary_key=True),
    Column("media_id", Integer, ForeignKey("media.id"), primary_key=True),
    Column("position", Integer)
)

CHANNEL_MODES = ("standard", "separate_audio")

class Playlist(Base):
    __tablename__ = "playlists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    # Whether the admin wants this channel on air; used to resume after restarts.
    stream_running = Column(Boolean, nullable=False, default=False, server_default='false')
    # "standard": each video plays with its own sound.
    # "separate_audio": video playlist and audio playlist loop independently, mixed live.
    mode = Column(String, nullable=False, default="standard", server_default="standard")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    media_items = relationship(
        "Media",
        secondary=playlist_media,
        order_by=playlist_media.c.position,
        backref="playlists"
    )

    audio_items = relationship(
        "Media",
        secondary=playlist_audio,
        order_by=playlist_audio.c.position,
    )
