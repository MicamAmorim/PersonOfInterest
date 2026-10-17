from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    location: str = Field(default="", max_length=120)
    rtsp_url: str = Field(min_length=7, max_length=2048)
    enabled: bool = True

    @field_validator("name", "location")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("rtsp_url")
    @classmethod
    def validate_rtsp(cls, value: str) -> str:
        value = value.strip()
        if not value.lower().startswith(("rtsp://", "rtsps://")):
            raise ValueError("A URL deve começar com rtsp:// ou rtsps://")
        return value


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    location: str | None = Field(default=None, max_length=120)
    rtsp_url: str | None = Field(default=None, min_length=7, max_length=2048)
    enabled: bool | None = None

    @field_validator("name", "location")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("rtsp_url")
    @classmethod
    def validate_optional_rtsp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value.lower().startswith(("rtsp://", "rtsps://")):
            raise ValueError("A URL deve começar com rtsp:// ou rtsps://")
        return value


class CameraOut(BaseModel):
    id: int
    name: str
    location: str
    stream_name: str
    enabled: bool
    rtsp_url_display: str
    has_credentials: bool
    sync_status: Literal["ok", "pending", "error", "disabled"] | str
    sync_error: str | None
    created_at: str
    updated_at: str
    viewer_url: str
