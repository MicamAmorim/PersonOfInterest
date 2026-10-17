from __future__ import annotations

import ipaddress
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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


class EventBulkDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)

    @field_validator("ids")
    @classmethod
    def unique_ids(cls, value: list[int]) -> list[int]:
        cleaned = sorted({int(item) for item in value if int(item) > 0})
        if not cleaned:
            raise ValueError("Selecione ao menos um evento")
        return cleaned


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class EventPersonAssignRequest(BaseModel):
    person_id: int | None = Field(default=None, ge=1)


class IdentityAssignRequest(BaseModel):
    person_id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def strip_identity_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def one_identity_target(self) -> "IdentityAssignRequest":
        if self.person_id is None and not self.name:
            raise ValueError("Informe uma pessoa existente ou um nome")
        return self


class PushSubscriptionRequest(BaseModel):
    endpoint: str = Field(min_length=8, max_length=4096)
    p256dh: str = Field(min_length=8, max_length=1024)
    auth: str = Field(min_length=4, max_length=512)
    expiration_time: float | None = None
    user_agent: str | None = Field(default=None, max_length=512)


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    camera_id: int | None = Field(default=None, ge=1)
    person_id: int | None = Field(default=None, ge=1)
    unknown_only: bool = False
    start_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    cooldown_seconds: int = Field(default=300, ge=0, le=86400)

    @field_validator("name", "timezone")
    @classmethod
    def strip_rule_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int]) -> list[int]:
        cleaned = sorted(set(int(day) for day in value))
        if not cleaned or any(day < 0 or day > 6 for day in cleaned):
            raise ValueError("Dias da semana devem estar entre 0 e 6")
        return cleaned

    @model_validator(mode="after")
    def validate_rule_scope(self) -> "AlertRuleCreate":
        if self.unknown_only and self.person_id is not None:
            raise ValueError("Uma regra não pode ser de desconhecidos e de uma pessoa específica ao mesmo tempo")
        if bool(self.start_time) != bool(self.end_time):
            raise ValueError("Informe horário inicial e final juntos")
        return self


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    camera_id: int | None = Field(default=None, ge=1)
    person_id: int | None = Field(default=None, ge=1)
    unknown_only: bool | None = None
    start_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    weekdays: list[int] | None = Field(default=None, min_length=1, max_length=7)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)

    @field_validator("name", "timezone")
    @classmethod
    def strip_optional_rule_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("weekdays")
    @classmethod
    def validate_optional_weekdays(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        cleaned = sorted(set(int(day) for day in value))
        if not cleaned or any(day < 0 or day > 6 for day in cleaned):
            raise ValueError("Dias da semana devem estar entre 0 e 6")
        return cleaned
