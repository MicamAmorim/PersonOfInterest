from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "PersonOfInterest"
APP_VERSION = "0.4.5.4"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
DB_PATH = DATA_DIR / "person_of_interest.db"
EVENTS_DIR = DATA_DIR / "events"
FACES_DIR = DATA_DIR / "faces"
MODELS_DIR = DATA_DIR / "models"
VAPID_DIR = DATA_DIR / "vapid"
ASSISTANT_AUDIO_DIR = DATA_DIR / "assistant_audio"
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

# Appearance ReID. Body evidence is *never* promoted to an absolute identity.
# It only fills probable_person_id and is visually labelled as "Provável".
BODY_REID_MODEL_PATH = Path(
    os.getenv("BODY_REID_MODEL_PATH", str(MODELS_DIR / "osnet_x0_25_msmt17.onnx"))
).resolve()
BODY_REID_THRESHOLD = float(os.getenv("BODY_REID_THRESHOLD", "0.72"))
BODY_REID_MARGIN = float(os.getenv("BODY_REID_MARGIN", "0.045"))
BODY_REID_FACE_BONUS = float(os.getenv("BODY_REID_FACE_BONUS", "0.035"))
BODY_REID_POLL_SECONDS = float(os.getenv("BODY_REID_POLL_SECONDS", "0.8"))

# Learned detector hard-negatives. Manual false-positive reviews become an
# appearance bank used only to reject future detections from the same camera.
# Two similar reviewed negatives are preferred; a single example is accepted
# only at a very high similarity and when the bounding boxes substantially
# overlap (useful for stationary objects such as dolls/plush toys).
BODY_NEGATIVE_THRESHOLD = float(os.getenv("BODY_NEGATIVE_THRESHOLD", "0.90"))
BODY_NEGATIVE_SINGLE_THRESHOLD = float(os.getenv("BODY_NEGATIVE_SINGLE_THRESHOLD", "0.965"))
BODY_NEGATIVE_MARGIN = float(os.getenv("BODY_NEGATIVE_MARGIN", "0.055"))
BODY_NEGATIVE_MIN_SUPPORT = int(os.getenv("BODY_NEGATIVE_MIN_SUPPORT", "2"))
BODY_NEGATIVE_BBOX_IOU = float(os.getenv("BODY_NEGATIVE_BBOX_IOU", "0.55"))
BODY_NEGATIVE_MIN_QUALITY = float(os.getenv("BODY_NEGATIVE_MIN_QUALITY", "0.30"))

# V4.2 camera assistant. A high-quality unknown face takes priority over body
# guesses, preserving the rule that face evidence is stronger than appearance.
ASSISTANT_POLL_SECONDS = float(os.getenv("ASSISTANT_POLL_SECONDS", "1.0"))
ASSISTANT_SETTLE_SECONDS = float(os.getenv("ASSISTANT_SETTLE_SECONDS", "12.0"))
ASSISTANT_UNKNOWN_FACE_QUALITY = float(os.getenv("ASSISTANT_UNKNOWN_FACE_QUALITY", "0.72"))

# V4.4/V4.5 local voice activation and short deterministic conversation.
# Tiny stays always-on as the cheap first pass. Base handles commands and V4.5.4
# may also rescue a missed wake word on short, clear speech. The base model is
# preloaded in the background only when a persisted wake listener is enabled.
WAKE_PHRASE = os.getenv("WAKE_PHRASE", "Oi, Tonho!")
WAKE_WHISPER_MODEL = os.getenv("WAKE_WHISPER_MODEL", "tiny")
WAKE_COMMAND_WHISPER_MODEL = os.getenv("WAKE_COMMAND_WHISPER_MODEL", "base")
WAKE_CHUNK_SECONDS = float(os.getenv("WAKE_CHUNK_SECONDS", "4.0"))
WAKE_OVERLAP_SECONDS = float(os.getenv("WAKE_OVERLAP_SECONDS", "0.8"))
WAKE_MIN_RMS = float(os.getenv("WAKE_MIN_RMS", "0.004"))
WAKE_RESPONSE_COOLDOWN_SECONDS = float(os.getenv("WAKE_RESPONSE_COOLDOWN_SECONDS", "0.35"))
WAKE_CONTEXT_SECONDS = float(os.getenv("WAKE_CONTEXT_SECONDS", "20.0"))
WAKE_AFTER_SPEECH_MUTE_SECONDS = float(os.getenv("WAKE_AFTER_SPEECH_MUTE_SECONDS", "0.35"))
WAKE_FOLLOWUP_GUARD_SECONDS = float(os.getenv("WAKE_FOLLOWUP_GUARD_SECONDS", "0.25"))
WAKE_CONVERSATION_SECONDS = float(os.getenv("WAKE_CONVERSATION_SECONDS", "10.0"))
WAKE_FALLBACK_STT_ENABLED = os.getenv("WAKE_FALLBACK_STT_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
WAKE_FALLBACK_MIN_RMS = float(os.getenv("WAKE_FALLBACK_MIN_RMS", "0.006"))
WAKE_FALLBACK_MAX_WORDS = int(os.getenv("WAKE_FALLBACK_MAX_WORDS", "8"))
WAKE_FALLBACK_COOLDOWN_SECONDS = float(os.getenv("WAKE_FALLBACK_COOLDOWN_SECONDS", "1.5"))

# V4 alerts / Web Push.
VAPID_PRIVATE_KEY_PATH = Path(
    os.getenv("VAPID_PRIVATE_KEY_PATH", str(VAPID_DIR / "private_key.pem"))
).resolve()
VAPID_PUBLIC_KEY_PATH = Path(
    os.getenv("VAPID_PUBLIC_KEY_PATH", str(VAPID_DIR / "public_key.txt"))
).resolve()
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:personofinterest@local.invalid")
ALERT_POLL_SECONDS = float(os.getenv("ALERT_POLL_SECONDS", "1.0"))
