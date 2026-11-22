"""Tests for sensor database setup and request/response validation."""

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from api.sensor_schemas import SensorReadingRequest
from api.sensor_store import database_connection, initialize_database


class SensorDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "sensor-test.sqlite3"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_initialization_creates_tables_and_indexes(self) -> None:
        initialize_database(self.database_path)

        with database_connection(self.database_path) as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            indexes = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )
            }

        self.assertIn("sensor_readings", tables)
        self.assertIn("sensor_alerts", tables)
        self.assertIn("uq_sensor_readings_device_reading", indexes)
        self.assertIn("uq_sensor_alerts_active_device_metric", indexes)

    def test_initialization_is_safe_to_repeat(self) -> None:
        initialize_database(self.database_path)
        initialize_database(self.database_path)

        with database_connection(self.database_path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM sqlite_master "
                "WHERE type = 'table' AND name IN (?, ?) ",
                ("sensor_readings", "sensor_alerts"),
            ).fetchone()["count"]

        self.assertEqual(count, 2)

    def test_foreign_keys_are_enabled_and_enforced(self) -> None:
        initialize_database(self.database_path)

        with database_connection(self.database_path) as connection:
            self.assertEqual(
                connection.execute("PRAGMA foreign_keys").fetchone()[0], 1
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO sensor_alerts (
                        device_id, reading_id, metric, observed_value,
                        threshold, severity, triggered_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "sensor-1", 999, "temperature", 36.0, 35.0,
                        "warning", "2026-11-01T00:00:00Z",
                    ),
                )

    def test_reading_id_is_unique_per_device_and_optional(self) -> None:
        initialize_database(self.database_path)

        with database_connection(self.database_path) as connection:
            reading = (
                "sensor-1", "sample-1", 22.0, 50.0, 1200,
                None, "2026-11-01T00:00:00Z",
            )
            insert = """
                INSERT INTO sensor_readings (
                    device_id, reading_id, temperature_c, humidity_percent,
                    gas_reading, measured_at, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            connection.execute(insert, reading)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(insert, reading)

            # The same key is independent across devices, and NULL keys do not
            # prevent readings that do not request idempotency.
            connection.execute(insert, ("sensor-2", *reading[1:]))
            connection.execute(insert, ("sensor-1", None, *reading[2:]))
            connection.execute(insert, ("sensor-1", None, *reading[2:]))

    def test_only_one_active_alert_per_device_and_metric(self) -> None:
        initialize_database(self.database_path)

        with database_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO sensor_readings (
                    device_id, temperature_c, humidity_percent, gas_reading,
                    received_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("sensor-1", 36.0, 50.0, 1200, "2026-11-01T00:00:00Z"),
            )
            alert = """
                INSERT INTO sensor_alerts (
                    device_id, reading_id, metric, observed_value, threshold,
                    severity, triggered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            values = (
                "sensor-1", 1, "temperature", 36.0, 35.0,
                "warning", "2026-11-01T00:00:00Z",
            )
            connection.execute(alert, values)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(alert, values)

            connection.execute(
                "UPDATE sensor_alerts SET cleared_at = ? WHERE id = 1",
                ("2026-11-01T00:05:00Z",),
            )
            connection.execute(alert, values)


class SensorReadingSchemaTests(unittest.TestCase):
    def valid_payload(self) -> dict[str, object]:
        return {
            "device_id": "wokwi-esp32-01",
            "reading_id": "boot-1:42",
            "temperature": 31.4,
            "humidity": 72.1,
            "gas_reading": 1840,
            "measured_at": "2026-11-01T10:20:30+05:30",
        }

    def test_valid_reading_and_optional_fields(self) -> None:
        reading = SensorReadingRequest.model_validate(self.valid_payload())
        self.assertEqual(reading.device_id, "wokwi-esp32-01")
        self.assertEqual(reading.gas_reading, 1840)
        self.assertEqual(reading.measured_at.utcoffset().total_seconds(), 0)

        without_optional_values = self.valid_payload()
        without_optional_values.pop("reading_id")
        without_optional_values.pop("measured_at")
        reading = SensorReadingRequest.model_validate(without_optional_values)
        self.assertIsNone(reading.reading_id)
        self.assertIsNone(reading.measured_at)

    def test_temperature_and_humidity_ranges(self) -> None:
        for field, value in (
            ("temperature", -40.1), ("temperature", 85.1),
            ("humidity", -0.1), ("humidity", 100.1),
        ):
            payload = self.valid_payload()
            payload[field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValidationError):
                    SensorReadingRequest.model_validate(payload)

    def test_gas_reading_must_be_integer_in_range(self) -> None:
        for value in (-1, 4096, 1.5, True):
            payload = self.valid_payload()
            payload["gas_reading"] = value
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    SensorReadingRequest.model_validate(payload)

    def test_non_finite_sensor_values_are_rejected(self) -> None:
        for field in ("temperature", "humidity"):
            for value in (float("nan"), float("inf"), float("-inf")):
                payload = self.valid_payload()
                payload[field] = value
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        SensorReadingRequest.model_validate(payload)

    def test_invalid_identifiers_are_rejected(self) -> None:
        for field, value in (
            ("device_id", ""),
            ("device_id", "bad id"),
            ("device_id", "x" * 65),
            ("reading_id", "x" * 129),
        ):
            payload = self.valid_payload()
            payload[field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValidationError):
                    SensorReadingRequest.model_validate(payload)

    def test_measured_at_must_be_timezone_aware(self) -> None:
        for timestamp in (
            "2026-11-01T10:20:30",
            datetime(2026, 11, 1, 10, 20, 30),
        ):
            payload = self.valid_payload()
            payload["measured_at"] = timestamp
            with self.subTest(timestamp=timestamp):
                with self.assertRaises(ValidationError):
                    SensorReadingRequest.model_validate(payload)

        payload = self.valid_payload()
        payload["measured_at"] = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.assertIsNotNone(
            SensorReadingRequest.model_validate(payload).measured_at
        )


if __name__ == "__main__":
    unittest.main()
