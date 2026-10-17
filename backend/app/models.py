from __future__ import annotations

import ipaddress
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


class DiscoveryProbeRequest(BaseModel):
    ip: str
    username: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=256)
    path: str | None = Field(default=None, max_length=512)
    port: int = Field(default=554, ge=1, le=65535)

    @field_validator("ip")
    @classmethod
    def validate_ip(cls, value: str) -> str:
        value = value.strip()
        address = ipaddress.ip_address(value)
        if address.version != 4 or not address.is_private:
            raise ValueError("Use um IPv4 privado da rede local")
        return value

    @field_validator("username", "password")
    @classmethod
    def strip_credentials(cls, value: str) -> str:
        return value.strip()

    @field_validator("path")
    @classmethod
    def normalize_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        return value if value.startswith("/") else f"/{value}"


class VisionFollowRequest(BaseModel):
    enabled: bool
    track_id: int | None = Field(default=None, ge=1)


class VisionSettingsUpdate(BaseModel):
    autofollow_max_speed: float = Field(ge=0.20, le=0.90)


class PTZMoveRequest(BaseModel):
    pan: float = Field(ge=-1.0, le=1.0)
    tilt: float = Field(ge=-1.0, le=1.0)
    speed: float = Field(default=0.55, ge=0.05, le=1.0)
    duration: float = Field(default=0.35, ge=0.1, le=2.0)
