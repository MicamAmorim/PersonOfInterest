from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "PersonOfInterest"
APP_VERSION = "0.2.0"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
DB_PATH = DATA_DIR / "person_of_interest.db"
EVENTS_DIR = DATA_DIR / "events"
GO2RTC_API_URL = os.getenv("GO2RTC_API_URL", "http://127.0.0.1:1984").rstrip("/")
GO2RTC_BROWSER_BASE = os.getenv("GO2RTC_BROWSER_BASE", "direct").rstrip("/")
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", str(PROJECT_ROOT / "frontend"))).resolve()
VISION_PROCESS_FPS = float(os.getenv("VISION_PROCESS_FPS", "1.4"))
VISION_MAX_WIDTH = int(os.getenv("VISION_MAX_WIDTH", "640"))
VISION_EVENT_COOLDOWN_SECONDS = float(os.getenv("VISION_EVENT_COOLDOWN_SECONDS", "8"))
PTZ_ONVIF_PORT = int(os.getenv("PTZ_ONVIF_PORT", "8899"))
