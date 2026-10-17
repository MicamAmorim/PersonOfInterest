from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "PersonOfInterest"
APP_VERSION = "0.1.0"
DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()
DB_PATH = DATA_DIR / "person_of_interest.db"
GO2RTC_API_URL = os.getenv("GO2RTC_API_URL", "http://go2rtc:1984").rstrip("/")
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", "/app/frontend"))
