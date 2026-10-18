from __future__ import annotations

from typing import Any

from . import wake_word as ww
from .config import (
    WAKE_COMMAND_WHISPER_MODEL,
    WAKE_WHISPER_MODEL,
    WHISPER_COMMAND_MODELS,
    WHISPER_WAKE_MODELS,
)
from .db import connection, utc_now


def _validate_model(name: str | None, allowed: tuple[str, ...], fallback: str) -> str:
    value = str(name or fallback).strip().lower()
    if value not in allowed:
        raise ValueError(f"Modelo Whisper inválido: {value}")
    return value


def _ensure_runtime(manager: Any) -> None:
    if not hasattr(manager, "_poi_model_cache"):
        manager._poi_model_cache = {}
    if not hasattr(manager, "_poi_model_states"):
        manager._poi_model_states = {}


def install() -> None:
    """Add per-camera Whisper choices and a shared local model cache.

    Existing databases are migrated in place. Loading a selected model through
    faster-whisper downloads it automatically when it is not already cached.
    """
    cls = ww.WakeWordManager
    if getattr(cls, "_poi_model_settings_patch", False):
        return

    original_ensure_schema = cls.ensure_schema
    original_settings_for = cls.settings_for
    original_update_setting = cls.update_setting
    original_enrich_settings = cls.enrich_settings
    original_enabled_cameras = cls._enabled_cameras
    original_state = cls.state

    def ensure_schema_with_models(self: Any) -> None:
        original_ensure_schema(self)
        with connection() as conn:
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(camera_wake_settings)").fetchall()
            }
            if "wake_model" not in columns:
                conn.execute(
                    f"ALTER TABLE camera_wake_settings ADD COLUMN wake_model TEXT NOT NULL DEFAULT '{WAKE_WHISPER_MODEL}'"
                )
            if "command_model" not in columns:
                conn.execute(
                    f"ALTER TABLE camera_wake_settings ADD COLUMN command_model TEXT NOT NULL DEFAULT '{WAKE_COMMAND_WHISPER_MODEL}'"
                )
            conn.execute(
                "UPDATE camera_wake_settings SET wake_model = ? WHERE wake_model IS NULL OR TRIM(wake_model) = ''",
                (WAKE_WHISPER_MODEL,),
            )
            conn.execute(
                "UPDATE camera_wake_settings SET command_model = ? WHERE command_model IS NULL OR TRIM(command_model) = ''",
                (WAKE_COMMAND_WHISPER_MODEL,),
            )
            conn.commit()

    def settings_for_with_models(self: Any, camera_id: int) -> dict[str, Any]:
        data = dict(original_settings_for(self, camera_id))
        with connection() as conn:
            row = conn.execute(
                "SELECT wake_model, command_model FROM camera_wake_settings WHERE camera_id = ?",
                (camera_id,),
            ).fetchone()
        data["wake_model"] = _validate_model(
            row["wake_model"] if row else None,
            WHISPER_WAKE_MODELS,
            WAKE_WHISPER_MODEL,
        )
        data["command_model"] = _validate_model(
            row["command_model"] if row else None,
            WHISPER_COMMAND_MODELS,
            WAKE_COMMAND_WHISPER_MODEL,
        )
        return data

    def update_setting_with_models(
        self: Any,
        camera_id: int,
        enabled: bool,
        wake_model: str | None = None,
        command_model: str | None = None,
    ) -> dict[str, Any]:
        original_update_setting(self, camera_id, enabled)
        current = settings_for_with_models(self, camera_id)
        selected_wake = _validate_model(
            wake_model if wake_model is not None else current.get("wake_model"),
            WHISPER_WAKE_MODELS,
            WAKE_WHISPER_MODEL,
        )
        selected_command = _validate_model(
            command_model if command_model is not None else current.get("command_model"),
            WHISPER_COMMAND_MODELS,
            WAKE_COMMAND_WHISPER_MODEL,
        )
        models_changed = (
            str(current.get("wake_model")) != selected_wake
            or str(current.get("command_model")) != selected_command
        )
        with connection() as conn:
            conn.execute(
                "UPDATE camera_wake_settings SET wake_model = ?, command_model = ?, updated_at = ? WHERE camera_id = ?",
                (selected_wake, selected_command, utc_now(), camera_id),
            )
            conn.commit()

        # Worker camera configuration is a snapshot. Restart only this listener
        # when models change so the new selection takes effect without requiring
        # a full PersonOfInterest restart.
        if models_changed:
            with self.lock:
                worker = self._workers.pop(camera_id, None)
            if worker is not None:
                _, stop = worker
                stop.set()
        self.notify_change()
        return settings_for_with_models(self, camera_id)

    def enrich_settings_with_models(self: Any, settings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        base = original_enrich_settings(self, settings)
        with connection() as conn:
            rows = conn.execute(
                "SELECT camera_id, wake_model, command_model FROM camera_wake_settings"
            ).fetchall()
        by_camera = {int(row["camera_id"]): row for row in rows}
        output: list[dict[str, Any]] = []
        for item in base:
            data = dict(item)
            row = by_camera.get(int(data["camera_id"]))
            data["wake_model"] = _validate_model(
                row["wake_model"] if row else None,
                WHISPER_WAKE_MODELS,
                WAKE_WHISPER_MODEL,
            )
            data["command_model"] = _validate_model(
                row["command_model"] if row else None,
                WHISPER_COMMAND_MODELS,
                WAKE_COMMAND_WHISPER_MODEL,
            )
            output.append(data)
        return output

    def enabled_cameras_with_models(self: Any) -> dict[int, dict[str, Any]]:
        cameras = original_enabled_cameras(self)
        for camera_id, camera in cameras.items():
            setting = settings_for_with_models(self, camera_id)
            camera["wake_model"] = setting["wake_model"]
            camera["command_model"] = setting["command_model"]
        return cameras

    def ensure_model_by_name(self: Any, model_name: str | None = None) -> Any:
        _ensure_runtime(self)
        name = str(model_name or WAKE_WHISPER_MODEL).strip().lower()
        allowed = tuple(dict.fromkeys((*WHISPER_WAKE_MODELS, *WHISPER_COMMAND_MODELS)))
        if name not in allowed:
            raise ValueError(f"Modelo Whisper inválido: {name}")
        cached = self._poi_model_cache.get(name)
        if cached is not None:
            return cached
        if not ww.WAKE_RUNTIME_AVAILABLE:
            raise RuntimeError(ww.WAKE_RUNTIME_ERROR or "faster-whisper indisponível")
        with self.model_lock:
            cached = self._poi_model_cache.get(name)
            if cached is not None:
                return cached
            previous = self.status
            self.status = f"loading_model:{name}"
            self._poi_model_states[name] = {"status": "loading", "error": None, "updated_at": utc_now()}
            try:
                model = ww.WhisperModel(name, device="cpu", compute_type="int8")
                self._poi_model_cache[name] = model
                self._poi_model_states[name] = {"status": "loaded", "error": None, "updated_at": utc_now()}
                if name == WAKE_WHISPER_MODEL:
                    self._model = model
                return model
            except Exception as exc:
                self._poi_model_states[name] = {"status": "error", "error": str(exc), "updated_at": utc_now()}
                raise
            finally:
                if str(self.status).startswith("loading_model:"):
                    self.status = previous if previous not in {"stopped", "error"} else "running"

    def transcribe_by_name(self: Any, audio: Any, model_name: str | None = None) -> str:
        name = str(model_name or WAKE_WHISPER_MODEL).strip().lower()
        model = ensure_model_by_name(self, name)
        with self.model_lock:
            segments, _ = model.transcribe(
                audio,
                language="pt",
                beam_size=1,
                best_of=1,
                temperature=0.0,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt="Frase de ativação: Oi, Tonho!",
            )
            return " ".join(
                segment.text.strip() for segment in segments if segment.text.strip()
            ).strip()

    def state_with_models(self: Any) -> dict[str, Any]:
        data = original_state(self)
        _ensure_runtime(self)
        data["model_options"] = {
            "wake": list(WHISPER_WAKE_MODELS),
            "command": list(WHISPER_COMMAND_MODELS),
        }
        data["model_defaults"] = {
            "wake": WAKE_WHISPER_MODEL,
            "command": WAKE_COMMAND_WHISPER_MODEL,
        }
        data["loaded_models"] = sorted(self._poi_model_cache)
        data["model_states"] = dict(self._poi_model_states)
        return data

    cls.ensure_schema = ensure_schema_with_models
    cls.settings_for = settings_for_with_models
    cls.update_setting = update_setting_with_models
    cls.enrich_settings = enrich_settings_with_models
    cls._enabled_cameras = enabled_cameras_with_models
    cls._ensure_model = ensure_model_by_name
    cls._transcribe = transcribe_by_name
    cls.state = state_with_models
    cls._poi_model_settings_patch = True
