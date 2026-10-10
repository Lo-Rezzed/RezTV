from sqlalchemy import Column, Integer, String, DateTime, Table, ForeignKey
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

class Playlist(Base):
    __tablename__ = "playlists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    media_items = relationship(
        "Media",
        secondary=playlist_media,
        order_by=playlist_media.c.position,
        backref="playlists"
    )
