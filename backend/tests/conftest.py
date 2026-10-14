import os
import sys

os.environ.setdefault("STATION_RESOLUTION", "320x240")
os.environ.setdefault("STATION_FPS", "30")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
