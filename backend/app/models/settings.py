from sqlalchemy import Boolean, Column, Integer, String
from app.core.database import Base

class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    station_name = Column(String, default="RezTV")
    # Scheduled station backups: every backup_interval_hours (0 = off), keep the newest
    # backup_keep scheduled ones. Manual backups are never deleted automatically.
    backup_interval_hours = Column(Integer, nullable=False, default=0, server_default="0")
    backup_keep = Column(Integer, nullable=False, default=7, server_default="7")
    backup_include_media = Column(Boolean, nullable=False, default=True, server_default="true")
