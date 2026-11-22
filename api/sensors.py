"""Environmental sensor ingestion endpoints."""

import logging
import os
import secrets
import sqlite3

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from api.sensor_schemas import (
    SensorAlertHistoryResponse,
    SensorReadingIngestResponse,
    SensorReadingRequest,
    SensorLatestResponse,
    SensorReadingHistoryResponse,
    SensorStatusResponse,
)
from api.sensor_store import (
    get_latest_sensor_readings,
    get_sensor_alert_history,
    get_sensor_reading_history,
    get_sensor_status,
    insert_sensor_reading,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sensors", tags=["sensors"])
_DEVICE_ID_QUERY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"


def _ensure_sensor_store_ready(request: Request) -> None:
    if not getattr(request.app.state, "sensor_store_ready", False):
        raise HTTPException(
            status_code=503,
            detail="Sensor storage is unavailable.",
        )


def _read_sensor_data(operation, *args):
    """Run a store query and keep SQLite/internal errors out of responses."""

    try:
        return operation(*args)
    except sqlite3.Error:
        logger.exception("SQLite failed while retrieving sensor data.")
        raise HTTPException(
            status_code=500,
            detail="Sensor data could not be retrieved.",
        ) from None
    except Exception:
        logger.exception("Unexpected error while retrieving sensor data.")
        raise HTTPException(
            status_code=500,
            detail="Sensor data could not be retrieved.",
        ) from None


def authenticate_device(
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
) -> None:
    """Require a configured server token and compare it without timing leaks."""

    expected_token = os.getenv("SENSOR_DEVICE_TOKEN")
    if not expected_token:
        raise HTTPException(
            status_code=401,
            detail="Sensor device authentication is not configured.",
        )

    if x_device_token is None or not secrets.compare_digest(
        x_device_token.encode("utf-8"), expected_token.encode("utf-8")
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing device token.",
        )


@router.post(
    "/readings",
    response_model=SensorReadingIngestResponse,
    status_code=201,
    summary="Ingest an environmental sensor reading",
)
def ingest_sensor_reading(
    reading: SensorReadingRequest,
    request: Request,
    response: Response,
    _device: None = Depends(authenticate_device),
) -> SensorReadingIngestResponse:
    """Validate, authenticate, and persist a single device reading."""

    _ensure_sensor_store_ready(request)

    try:
        # FastAPI dispatches synchronous handlers to its worker thread pool,
        # keeping SQLite calls off the async event loop.
        stored_reading, inserted, active_alerts = insert_sensor_reading(reading)
    except sqlite3.Error:
        logger.exception("SQLite failed while storing a sensor reading.")
        raise HTTPException(
            status_code=500,
            detail="The sensor reading could not be stored.",
        ) from None
    except Exception:
        logger.exception("Unexpected error while storing a sensor reading.")
        raise HTTPException(
            status_code=500,
            detail="The sensor reading could not be stored.",
        ) from None

    if not inserted:
        response.status_code = 200

    return SensorReadingIngestResponse(
        id=stored_reading.id,
        device_id=stored_reading.device_id,
        received_at=stored_reading.received_at,
        active_alerts=active_alerts,
    )


@router.get("/latest", response_model=SensorLatestResponse)
def latest_sensor_readings(
    request: Request,
    device_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=64,
        pattern=_DEVICE_ID_QUERY_PATTERN,
    ),
) -> SensorLatestResponse:
    """Get the latest reading for one device or each device with readings."""

    _ensure_sensor_store_ready(request)
    return _read_sensor_data(get_latest_sensor_readings, device_id)


@router.get("/history", response_model=SensorReadingHistoryResponse)
def sensor_reading_history(
    request: Request,
    device_id: str = Query(
        ...,
        min_length=1,
        max_length=64,
        pattern=_DEVICE_ID_QUERY_PATTERN,
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SensorReadingHistoryResponse:
    """Get a page of readings for one device, newest first."""

    _ensure_sensor_store_ready(request)
    return _read_sensor_data(
        get_sensor_reading_history,
        device_id,
        limit,
        offset,
    )


@router.get("/alerts", response_model=SensorAlertHistoryResponse)
def sensor_alert_history(
    request: Request,
    device_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=64,
        pattern=_DEVICE_ID_QUERY_PATTERN,
    ),
    active_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SensorAlertHistoryResponse:
    """Get active and cleared alert episodes, newest first."""

    _ensure_sensor_store_ready(request)
    return _read_sensor_data(
        get_sensor_alert_history,
        device_id,
        active_only,
        limit,
        offset,
    )


@router.get("/status", response_model=SensorStatusResponse)
def sensor_status(
    request: Request,
    device_id: str | None = Query(
        default=None,
        min_length=1,
        max_length=64,
        pattern=_DEVICE_ID_QUERY_PATTERN,
    ),
) -> SensorStatusResponse:
    """Return latest and last-seen data without inferring connectivity."""

    _ensure_sensor_store_ready(request)
    return _read_sensor_data(get_sensor_status, device_id)
