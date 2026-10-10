from sqlalchemy import Column, Integer, String
from app.core.database import Base

class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    station_name = Column(String, default="RezTV")
