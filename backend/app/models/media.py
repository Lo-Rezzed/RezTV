from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean
from sqlalchemy.sql import func
from app.core.database import Base

class Media(Base):
    __tablename__ = "media"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    title = Column(String, nullable=True)
    duration = Column(Float, nullable=True)          # in seconds
    filepath = Column(String, nullable=False)
    # "video" (plays on screen) or "audio" (music for separate-audio channels).
    kind = Column(String, nullable=False, default="video", server_default="video")
    folder = Column(String, nullable=False, default="Unsorted", server_default="Unsorted")
    # Conversion: pending -> converting -> ready | failed. Only "ready" media can be streamed.
    status = Column(String, nullable=False, default="pending", server_default="ready")
    error = Column(String, nullable=True)
    original_path = Column(String, nullable=True)   # uploaded file, kept only if KEEP_ORIGINALS
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # Audio rotation: a disabled track stays in the library and on channel lists but
    # is skipped when choosing what to play.
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    # Where `duration` came from: "measured" = scanned from the converted station
    # file; NULL = file metadata (old uploads, or not converted yet).
    duration_source = Column(String, nullable=True)
    # Optional tag: "vocals" (has lyrics), "instrumental", or NULL (not tagged).
    vocals = Column(String, nullable=True)

