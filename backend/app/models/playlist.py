from sqlalchemy import Column, Integer, String, DateTime, Boolean, Table, ForeignKey, Float
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

CHANNEL_MODES = ("standard", "separate_audio", "mixed")
DEFAULT_FILLER_MINUTES = 30
DEFAULT_REPEAT_GAP_TRACKS = 10
DEFAULT_REPEAT_GAP_MINUTES = 60

class Playlist(Base):
    __tablename__ = "playlists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    # Whether the admin wants this channel on air; used to resume after restarts.
    stream_running = Column(Boolean, nullable=False, default=False, server_default='false')
    # "standard": each video plays with its own sound.
    # "separate_audio": video playlist and audio playlist loop independently, mixed live.
    # "mixed": alternates one video from the video playlist (a rendered program with
    #   its own sound) with a filler block: shuffled clips from filler_folder, muted,
    #   under the audio playlist, for filler_minutes. Then the next program, and so on.
    mode = Column(String, nullable=False, default="standard", server_default="standard")
    filler_folder = Column(String, nullable=True)
    filler_minutes = Column(Integer, nullable=False, default=DEFAULT_FILLER_MINUTES,
                            server_default=str(DEFAULT_FILLER_MINUTES))
    # Separate-audio playback (separate_audio channels, mixed filler blocks): draw the
    # clip's media ID bottom left and the song title bottom right.
    show_overlay = Column(Boolean, nullable=False, default=True, server_default="true")
    # Music source: when set, the channel's music is every ready, enabled audio track
    # in this folder (new uploads join automatically) instead of the hand-made list.
    audio_folder = Column(String, nullable=True)
    # Music rotation: shuffle, and don't replay a track within the last
    # repeat_gap_tracks songs or repeat_gap_minutes minutes (0 = off).
    audio_shuffle = Column(Boolean, nullable=False, default=False, server_default="false")
    repeat_gap_tracks = Column(Integer, nullable=False, default=DEFAULT_REPEAT_GAP_TRACKS,
                               server_default=str(DEFAULT_REPEAT_GAP_TRACKS))
    repeat_gap_minutes = Column(Integer, nullable=False, default=DEFAULT_REPEAT_GAP_MINUTES,
                                server_default=str(DEFAULT_REPEAT_GAP_MINUTES))
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


class PlayHistory(Base):
    """One row per song played on a channel (music only). No foreign keys, so the
    history survives deleting a track or channel and restores cleanly."""
    __tablename__ = "play_history"

    id = Column(Integer, primary_key=True, index=True)
    playlist_id = Column(Integer, nullable=False, index=True)
    media_id = Column(Integer, nullable=True, index=True)
    title = Column(String, nullable=True)
    mode = Column(String, nullable=True)          # "separate_audio" or "mixed"
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    planned_seconds = Column(Float, nullable=True)   # the track's stored duration
    played_seconds = Column(Float, nullable=True)
    # "playing" (still on air), "natural" (played to its end) or "cut" (stopped early)
    outcome = Column(String, nullable=False, default="playing", server_default="playing")
    reason = Column(String, nullable=True)        # why it was cut: stopped, restart, ffmpeg exit...
