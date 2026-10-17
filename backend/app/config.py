from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "PersonOfInterest"
APP_VERSION = "0.2.2"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
DB_PATH = DATA_DIR / "person_of_interest.db"
EVENTS_DIR = DATA_DIR / "events"
MODELS_DIR = DATA_DIR / "models"
GO2RTC_API_URL = os.getenv("GO2RTC_API_URL", "http://127.0.0.1:1984").rstrip("/")
GO2RTC_BROWSER_BASE = os.getenv("GO2RTC_BROWSER_BASE", "direct").rstrip("/")
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", str(PROJECT_ROOT / "frontend"))).resolve()
# A slightly higher observation rate gives the motion estimator enough samples
# to estimate target velocity without making the ONNX workload excessive.
VISION_PROCESS_FPS = float(os.getenv("VISION_PROCESS_FPS", "2.5"))
VISION_MAX_WIDTH = int(os.getenv("VISION_MAX_WIDTH", "640"))
VISION_MODEL_PATH = Path(os.getenv("VISION_MODEL_PATH", str(MODELS_DIR / "yolox_tiny.onnx"))).resolve()
VISION_PERSON_CONFIDENCE = float(os.getenv("VISION_PERSON_CONFIDENCE", "0.42"))
# ByteTrack-style second association: these detections may maintain an existing
# track through blur/partial occlusion, but they never create a new person.
VISION_TRACK_LOW_CONFIDENCE = float(os.getenv("VISION_TRACK_LOW_CONFIDENCE", "0.20"))
VISION_NMS_THRESHOLD = float(os.getenv("VISION_NMS_THRESHOLD", "0.45"))
VISION_PREDICTION_HORIZON = float(os.getenv("VISION_PREDICTION_HORIZON", "0.38"))
VISION_MAX_TARGET_SPEED = float(os.getenv("VISION_MAX_TARGET_SPEED", "1.20"))
VISION_AUTOFOLLOW_MAX_SPEED = float(os.getenv("VISION_AUTOFOLLOW_MAX_SPEED", "0.46"))
# Zero by default: each stable track gets its own timeline event, including
# multiple people entering the frame at nearly the same time.
VISION_EVENT_COOLDOWN_SECONDS = float(os.getenv("VISION_EVENT_COOLDOWN_SECONDS", "0"))
PTZ_ONVIF_PORT = int(os.getenv("PTZ_ONVIF_PORT", "8899"))
