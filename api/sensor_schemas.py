"""Pydantic models for environmental sensor data."""

import math
import re
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


_DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_READING_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class SensorReadingRequest(BaseModel):
    """One environmental reading submitted by a sensor device.

    Request fields map to storage as follows: ``temperature`` to
    ``temperature_c``, ``humidity`` to ``humidity_percent``, and
    ``measured_at`` to the same-named UTC timestamp column. ``gas_reading``
    is retained as a raw simulated/proxy value; it is not a gas concentration.
    """

    model_config = ConfigDict(extra="forbid")

    device_id: Annotated[
        str,
        Field(min_length=1, max_length=64, pattern=_DEVICE_ID_PATTERN.pattern),
    ]
    reading_id: Annotated[
        str | None,
        Field(default=None, min_length=1, max_length=128, pattern=_READING_ID_PATTERN.pattern),
    ]
    temperature: Annotated[float, Field(ge=-40, le=85, allow_inf_nan=False)]
    humidity: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
    gas_reading: Annotated[int, Field(strict=True, ge=0, le=4095)]
    measured_at: datetime | None = None

    @field_validator("device_id", "reading_id", mode="before")
    @classmethod
    def trim_identifiers(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("temperature", "humidity", mode="before")
    @classmethod
    def reject_boolean_readings(cls, value: object) -> object:
        # bool is a subclass of int in Python, but it is not a sensor value.
        if isinstance(value, bool):
            raise ValueError("Sensor readings must be numeric values, not booleans.")
        return value

    @field_validator("temperature", "humidity")
    @classmethod
    def require_finite_readings(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Sensor readings must be finite numbers.")
        return value

    @field_validator("measured_at")
    @classmethod
    def require_timezone_aware_timestamp(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("measured_at must include a timezone.")
        return value.astimezone(timezone.utc) if value is not None else None


class SensorReadingResponse(BaseModel):
    """Sensor reading response using explicit database-oriented names."""

    model_config = ConfigDict(extra="forbid")

    id: int
    device_id: str
    reading_id: str | None
    temperature_c: float
    humidity_percent: float
    gas_reading: int
    measured_at: datetime | None
    received_at: datetime


class SensorAlertResponse(BaseModel):
    """A warning episode associated with an environmental sensor reading."""

    model_config = ConfigDict(extra="forbid")

    id: int
    device_id: str
    reading_id: int
    metric: Literal["temperature", "humidity", "gas_proxy"]
    observed_value: float
    threshold: float
    severity: Literal["warning"]
    triggered_at: datetime
    cleared_at: datetime | None


class SensorReadingIngestResponse(BaseModel):
    """Acknowledgement returned by the sensor ingestion endpoint."""

    model_config = ConfigDict(extra="forbid")

    id: int
    device_id: str
    received_at: datetime
    active_alerts: list[SensorAlertResponse] = Field(default_factory=list)


class SensorLatestDeviceResponse(BaseModel):
    """Latest reading for one requested or known device."""

    device_id: str
    latest_reading: SensorReadingResponse | None


class SensorLatestResponse(BaseModel):
    """Latest-reading results; the list is empty when no devices are known."""

    items: list[SensorLatestDeviceResponse]


class SensorReadingHistoryResponse(BaseModel):
    """A page of sensor readings and its total matching count."""

    items: list[SensorReadingResponse]
    total: int
    limit: int
    offset: int


class SensorAlertHistoryResponse(BaseModel):
    """A page of alert episodes and its total matching count."""

    items: list[SensorAlertResponse]
    total: int
    limit: int
    offset: int


class SensorDeviceStatusResponse(BaseModel):
    """Last-seen information and current environmental alerts for a device."""

    device_id: str
    latest_reading: SensorReadingResponse | None
    last_received_at: datetime | None
    active_alerts: list[SensorAlertResponse]


class SensorStatusResponse(BaseModel):
    """Status results without inferring online/offline connectivity."""

    items: list[SensorDeviceStatusResponse]
