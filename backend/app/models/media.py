from sqlalchemy import Column, Integer, String, DateTime, Float
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
    folder = Column(String, nullable=False, default="Unsorted", server_default="Unsorted")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
