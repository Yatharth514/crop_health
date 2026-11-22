"""SQLite database foundation for environmental sensor monitoring."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from api.sensor_schemas import (
    SensorAlertHistoryResponse,
    SensorAlertResponse,
    SensorDeviceStatusResponse,
    SensorLatestDeviceResponse,
    SensorLatestResponse,
    SensorReadingRequest,
    SensorReadingHistoryResponse,
    SensorReadingResponse,
    SensorStatusResponse,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "sensor_monitoring.sqlite3"
DATABASE_ENV_VAR = "SENSOR_DATABASE_PATH"
BUSY_TIMEOUT_SECONDS = 5.0
BUSY_TIMEOUT_MILLISECONDS = int(BUSY_TIMEOUT_SECONDS * 1000)
ALERT_THRESHOLDS: dict[str, float] = {
    "temperature": 35.0,
    "humidity": 80.0,
    "gas_proxy": 3000.0,
}


def get_database_path(database_path: str | Path | None = None) -> Path:
    """Resolve a caller-supplied path, environment path, or project default."""

    if database_path is not None:
        return Path(database_path).expanduser().resolve()

    configured_path = os.getenv(DATABASE_ENV_VAR)
    if configured_path:
        return Path(configured_path).expanduser().resolve()

    return DEFAULT_DATABASE_PATH


@contextmanager
def database_connection(
    database_path: str | Path | None = None,
) -> Iterator[sqlite3.Connection]:
    """Yield a configured connection and always commit/rollback and close it."""

    path = get_database_path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        path,
        timeout=BUSY_TIMEOUT_SECONDS,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MILLISECONDS}"
    )

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(database_path: str | Path | None = None) -> Path:
    """Create the sensor tables and indexes; safe to call repeatedly.

    Timestamps are stored as ISO 8601 text normalized to UTC by the API/store
    caller. ``received_at`` records server receipt time; ``measured_at`` may be
    null when a device does not have a synchronized clock.
    """

    path = get_database_path(database_path)

    with database_connection(path) as connection:
        # WAL allows readers to continue while a sensor write is in progress.
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id INTEGER PRIMARY KEY,
                device_id TEXT NOT NULL,
                reading_id TEXT,
                temperature_c REAL NOT NULL
                    CHECK (temperature_c >= -40 AND temperature_c <= 85),
                humidity_percent REAL NOT NULL
                    CHECK (humidity_percent >= 0 AND humidity_percent <= 100),
                gas_reading INTEGER NOT NULL
                    CHECK (gas_reading >= 0 AND gas_reading <= 4095),
                measured_at TEXT,
                received_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sensor_alerts (
                id INTEGER PRIMARY KEY,
                device_id TEXT NOT NULL,
                reading_id INTEGER NOT NULL,
                metric TEXT NOT NULL
                    CHECK (metric IN ('temperature', 'humidity', 'gas_proxy')),
                observed_value REAL NOT NULL,
                threshold REAL NOT NULL,
                severity TEXT NOT NULL CHECK (severity = 'warning'),
                triggered_at TEXT NOT NULL,
                cleared_at TEXT,
                FOREIGN KEY (reading_id)
                    REFERENCES sensor_readings(id) ON DELETE RESTRICT
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                uq_sensor_readings_device_reading
            ON sensor_readings (device_id, reading_id)
            WHERE reading_id IS NOT NULL
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_sensor_readings_device_received
            ON sensor_readings (device_id, received_at DESC, id DESC)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS ix_sensor_alerts_device_triggered
            ON sensor_alerts (device_id, triggered_at DESC, id DESC)
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                uq_sensor_alerts_active_device_metric
            ON sensor_alerts (device_id, metric)
            WHERE cleared_at IS NULL
            """
        )

    return path


def utc_timestamp_text(value: datetime) -> str:
    """Serialize a timezone-aware timestamp as UTC ISO 8601 text."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def insert_sensor_reading(
    reading: SensorReadingRequest,
    database_path: str | Path | None = None,
) -> tuple[SensorReadingResponse, bool, list[SensorAlertResponse]]:
    """Persist a reading and reconcile alert episodes in one transaction.

    The idempotency key is scoped to ``device_id``. A repeated key returns the
    original row, does not replace its values or receipt timestamp, and does
    not evaluate thresholds a second time. The returned boolean indicates
    whether a row was inserted; active alerts reflect the device's state after
    this call.
    """

    received_at = utc_timestamp_text(datetime.now(timezone.utc))
    measured_at = (
        utc_timestamp_text(reading.measured_at)
        if reading.measured_at is not None
        else None
    )

    with database_connection(database_path) as connection:
        values = (
            reading.device_id,
            reading.reading_id,
            reading.temperature,
            reading.humidity,
            reading.gas_reading,
            measured_at,
            received_at,
        )

        if reading.reading_id is not None:
            cursor = connection.execute(
                """
                INSERT INTO sensor_readings (
                    device_id, reading_id, temperature_c, humidity_percent,
                    gas_reading, measured_at, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (device_id, reading_id)
                    WHERE reading_id IS NOT NULL
                DO NOTHING
                """,
                values,
            )
            inserted = cursor.rowcount == 1
            if inserted:
                row = connection.execute(
                    "SELECT * FROM sensor_readings WHERE id = ?",
                    (cursor.lastrowid,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT * FROM sensor_readings
                    WHERE device_id = ? AND reading_id = ?
                    """,
                    (reading.device_id, reading.reading_id),
                ).fetchone()
        else:
            cursor = connection.execute(
                """
                INSERT INTO sensor_readings (
                    device_id, reading_id, temperature_c, humidity_percent,
                    gas_reading, measured_at, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            inserted = True
            row = connection.execute(
                "SELECT * FROM sensor_readings WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()

        if row is None:
            raise RuntimeError("Persisted sensor reading could not be retrieved.")

        stored_reading = SensorReadingResponse.model_validate(dict(row))

        if inserted:
            metric_values = {
                "temperature": reading.temperature,
                "humidity": reading.humidity,
                "gas_proxy": reading.gas_reading,
            }

            for metric, observed_value in metric_values.items():
                threshold = ALERT_THRESHOLDS[metric]
                active_alert = connection.execute(
                    """
                    SELECT id FROM sensor_alerts
                    WHERE device_id = ? AND metric = ? AND cleared_at IS NULL
                    """,
                    (reading.device_id, metric),
                ).fetchone()

                if observed_value > threshold:
                    if active_alert is None:
                        connection.execute(
                            """
                            INSERT INTO sensor_alerts (
                                device_id, reading_id, metric, observed_value,
                                threshold, severity, triggered_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                reading.device_id,
                                stored_reading.id,
                                metric,
                                observed_value,
                                threshold,
                                "warning",
                                utc_timestamp_text(stored_reading.received_at),
                            ),
                        )
                elif active_alert is not None:
                    connection.execute(
                        """
                        UPDATE sensor_alerts
                        SET cleared_at = ?
                        WHERE id = ? AND cleared_at IS NULL
                        """,
                        (
                            utc_timestamp_text(stored_reading.received_at),
                            active_alert["id"],
                        ),
                    )

        active_alert_rows = connection.execute(
            """
            SELECT * FROM sensor_alerts
            WHERE device_id = ? AND cleared_at IS NULL
            ORDER BY triggered_at ASC, id ASC
            """,
            (reading.device_id,),
        ).fetchall()
        active_alerts = [
            SensorAlertResponse.model_validate(dict(alert))
            for alert in active_alert_rows
        ]

        return stored_reading, inserted, active_alerts


def get_latest_sensor_readings(
    device_id: str | None = None,
    database_path: str | Path | None = None,
) -> SensorLatestResponse:
    """Get one latest reading for a device or each device with readings.

    Without a device registry table, devices known to the application are
    inferred from distinct device IDs in ``sensor_readings``. An explicit
    unknown device still returns one item with ``latest_reading=None``.
    """

    with database_connection(database_path) as connection:
        if device_id is not None:
            rows = connection.execute(
                """
                SELECT * FROM sensor_readings
                WHERE device_id = ?
                ORDER BY received_at DESC, id DESC
                LIMIT 1
                """,
                (device_id,),
            ).fetchall()
            return SensorLatestResponse(
                items=[
                    SensorLatestDeviceResponse(
                        device_id=device_id,
                        latest_reading=(
                            SensorReadingResponse.model_validate(dict(rows[0]))
                            if rows
                            else None
                        ),
                    )
                ]
            )

        rows = connection.execute(
            """
            SELECT * FROM (
                SELECT sensor_readings.*,
                    ROW_NUMBER() OVER (
                        PARTITION BY device_id
                        ORDER BY received_at DESC, id DESC
                    ) AS reading_rank
                FROM sensor_readings
            )
            WHERE reading_rank = 1
            ORDER BY device_id ASC
            """
        ).fetchall()

    return SensorLatestResponse(
        items=[
            SensorLatestDeviceResponse(
                device_id=row["device_id"],
                latest_reading=SensorReadingResponse.model_validate(
                    {key: row[key] for key in SensorReadingResponse.model_fields}
                ),
            )
            for row in rows
        ]
    )


def get_sensor_reading_history(
    device_id: str,
    limit: int = 20,
    offset: int = 0,
    database_path: str | Path | None = None,
) -> SensorReadingHistoryResponse:
    """Return newest-first sensor readings for a device with total count."""

    with database_connection(database_path) as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM sensor_readings WHERE device_id = ?",
            (device_id,),
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT * FROM sensor_readings
            WHERE device_id = ?
            ORDER BY received_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (device_id, limit, offset),
        ).fetchall()

    return SensorReadingHistoryResponse(
        items=[SensorReadingResponse.model_validate(dict(row)) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_sensor_alert_history(
    device_id: str | None = None,
    active_only: bool = False,
    limit: int = 20,
    offset: int = 0,
    database_path: str | Path | None = None,
) -> SensorAlertHistoryResponse:
    """Return newest-first alert episodes with optional filtering."""

    filters: list[str] = []
    parameters: list[object] = []
    if device_id is not None:
        filters.append("device_id = ?")
        parameters.append(device_id)
    if active_only:
        filters.append("cleared_at IS NULL")
    where_clause = " AND ".join(filters) if filters else "1 = 1"

    with database_connection(database_path) as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM sensor_alerts WHERE {where_clause}",
            parameters,
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT * FROM sensor_alerts
            WHERE {where_clause}
            ORDER BY triggered_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (*parameters, limit, offset),
        ).fetchall()

    return SensorAlertHistoryResponse(
        items=[SensorAlertResponse.model_validate(dict(row)) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_sensor_status(
    device_id: str | None = None,
    database_path: str | Path | None = None,
) -> SensorStatusResponse:
    """Return latest/last-seen data and active alerts, without freshness claims.

    A requested device with no readings is returned with null last-seen fields.
    When omitted, known devices are those present in the readings table.
    """

    with database_connection(database_path) as connection:
        if device_id is None:
            device_rows = connection.execute(
                "SELECT DISTINCT device_id FROM sensor_readings ORDER BY device_id"
            ).fetchall()
            device_ids = [row["device_id"] for row in device_rows]
            latest_rows = connection.execute(
                """
                SELECT id, device_id, reading_id, temperature_c,
                    humidity_percent, gas_reading, measured_at, received_at
                FROM (
                    SELECT sensor_readings.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY device_id
                            ORDER BY received_at DESC, id DESC
                        ) AS reading_rank
                    FROM sensor_readings
                )
                WHERE reading_rank = 1
                """
            ).fetchall()
            alert_rows = connection.execute(
                """
                SELECT * FROM sensor_alerts
                WHERE cleared_at IS NULL
                ORDER BY triggered_at ASC, id ASC
                """
            ).fetchall()
        else:
            device_ids = [device_id]
            latest_rows = connection.execute(
                """
                SELECT * FROM sensor_readings
                WHERE device_id = ?
                ORDER BY received_at DESC, id DESC
                LIMIT 1
                """,
                (device_id,),
            ).fetchall()
            alert_rows = connection.execute(
                """
                SELECT * FROM sensor_alerts
                WHERE device_id = ? AND cleared_at IS NULL
                ORDER BY triggered_at ASC, id ASC
                """,
                (device_id,),
            ).fetchall()

    latest_by_device = {
        row["device_id"]: SensorReadingResponse.model_validate(
            {key: row[key] for key in SensorReadingResponse.model_fields}
        )
        for row in latest_rows
    }
    alerts_by_device: dict[str, list[SensorAlertResponse]] = {}
    for row in alert_rows:
        alerts_by_device.setdefault(row["device_id"], []).append(
            SensorAlertResponse.model_validate(dict(row))
        )

    items: list[SensorDeviceStatusResponse] = []
    for current_device_id in device_ids:
        latest = latest_by_device.get(current_device_id)
        items.append(
            SensorDeviceStatusResponse(
                device_id=current_device_id,
                latest_reading=latest,
                last_received_at=latest.received_at if latest else None,
                active_alerts=alerts_by_device.get(current_device_id, []),
            )
        )

    return SensorStatusResponse(items=items)
