from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "PersonOfInterest"
APP_VERSION = "0.4.0"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
DB_PATH = DATA_DIR / "person_of_interest.db"
EVENTS_DIR = DATA_DIR / "events"
FACES_DIR = DATA_DIR / "faces"
MODELS_DIR = DATA_DIR / "models"
VAPID_DIR = DATA_DIR / "vapid"
GO2RTC_API_URL = os.getenv("GO2RTC_API_URL", "http://127.0.0.1:1984").rstrip("/")
GO2RTC_BROWSER_BASE = os.getenv("GO2RTC_BROWSER_BASE", "direct").rstrip("/")
FRONTEND_DIR = Path(os.getenv("FRONTEND_DIR", str(PROJECT_ROOT / "frontend"))).resolve()

# Detection / tracking
VISION_PROCESS_FPS = float(os.getenv("VISION_PROCESS_FPS", "4.0"))
VISION_MAX_WIDTH = int(os.getenv("VISION_MAX_WIDTH", "640"))
VISION_MODEL_PATH = Path(os.getenv("VISION_MODEL_PATH", str(MODELS_DIR / "yolox_tiny.onnx"))).resolve()
VISION_PERSON_CONFIDENCE = float(os.getenv("VISION_PERSON_CONFIDENCE", "0.42"))
VISION_TRACK_LOW_CONFIDENCE = float(os.getenv("VISION_TRACK_LOW_CONFIDENCE", "0.20"))
VISION_NMS_THRESHOLD = float(os.getenv("VISION_NMS_THRESHOLD", "0.45"))
VISION_PREDICTION_HORIZON = float(os.getenv("VISION_PREDICTION_HORIZON", "0.34"))
VISION_MAX_TARGET_SPEED = float(os.getenv("VISION_MAX_TARGET_SPEED", "1.20"))
VISION_FACE_SEARCH_AFTER = float(os.getenv("VISION_FACE_SEARCH_AFTER", "0.65"))
VISION_FACE_SEARCH_MAX_SPEED = float(os.getenv("VISION_FACE_SEARCH_MAX_SPEED", "0.30"))
VISION_AUTOFOLLOW_MAX_SPEED = float(os.getenv("VISION_AUTOFOLLOW_MAX_SPEED", "0.90"))
VISION_EVENT_COOLDOWN_SECONDS = float(os.getenv("VISION_EVENT_COOLDOWN_SECONDS", "0"))
PTZ_ONVIF_PORT = int(os.getenv("PTZ_ONVIF_PORT", "8899"))

# V3 identity. YuNet finds/alines faces and SFace produces compact embeddings.
FACE_DETECTOR_MODEL_PATH = Path(
    os.getenv("FACE_DETECTOR_MODEL_PATH", str(MODELS_DIR / "face_detection_yunet_2023mar.onnx"))
).resolve()
FACE_RECOGNIZER_MODEL_PATH = Path(
    os.getenv("FACE_RECOGNIZER_MODEL_PATH", str(MODELS_DIR / "face_recognition_sface_2021dec.onnx"))
).resolve()
IDENTITY_FACE_SCORE_THRESHOLD = float(os.getenv("IDENTITY_FACE_SCORE_THRESHOLD", "0.86"))
IDENTITY_KNOWN_THRESHOLD = float(os.getenv("IDENTITY_KNOWN_THRESHOLD", "0.48"))
IDENTITY_CLUSTER_THRESHOLD = float(os.getenv("IDENTITY_CLUSTER_THRESHOLD", "0.46"))
IDENTITY_POLL_SECONDS = float(os.getenv("IDENTITY_POLL_SECONDS", "1.0"))
IDENTITY_BATCH_SIZE = int(os.getenv("IDENTITY_BATCH_SIZE", "6"))

# V4 alerts / Web Push.
VAPID_PRIVATE_KEY_PATH = Path(
    os.getenv("VAPID_PRIVATE_KEY_PATH", str(VAPID_DIR / "private_key.pem"))
).resolve()
VAPID_PUBLIC_KEY_PATH = Path(
    os.getenv("VAPID_PUBLIC_KEY_PATH", str(VAPID_DIR / "public_key.txt"))
).resolve()
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:personofinterest@local.invalid")
ALERT_POLL_SECONDS = float(os.getenv("ALERT_POLL_SECONDS", "1.0"))
