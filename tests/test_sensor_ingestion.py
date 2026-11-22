"""Tests for authenticated sensor ingestion with isolated SQLite files."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from api.sensor_store import database_connection


class SensorIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "ingestion-test.sqlite3"
        self.environment = patch.dict(
            os.environ,
            {
                "SENSOR_DATABASE_PATH": str(self.database_path),
                "SENSOR_DEVICE_TOKEN": "temporary-test-device-token",
            },
        )
        self.environment.start()
        self.model_loader = patch("api.main.load_rf_predictor", return_value=object())
        self.model_loader.start()
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.model_loader.stop()
        self.environment.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def valid_payload(**updates: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "device_id": "wokwi-esp32-01",
            "reading_id": "boot-uuid:1042",
            "temperature": 31.4,
            "humidity": 72.1,
            "gas_reading": 1840,
            "measured_at": "2026-11-01T10:20:30Z",
        }
        payload.update(updates)
        return payload

    def ingest(self, payload=None, token="temporary-test-device-token"):
        """Submit a request through the registered FastAPI application."""

        headers = {} if token is None else {"X-Device-Token": token}
        response = self.client.post(
            "/api/sensors/readings",
            json=self.valid_payload() if payload is None else payload,
            headers=headers,
        )
        return response.status_code, response.json()

    def test_valid_authenticated_reading_is_created_and_persisted(self) -> None:
        status_code, body = self.ingest()

        self.assertEqual(status_code, 201)
        self.assertGreater(body["id"], 0)
        self.assertEqual(body["device_id"], "wokwi-esp32-01")
        self.assertTrue(body["received_at"].endswith("Z"))
        self.assertEqual(body["active_alerts"], [])

        with database_connection(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM sensor_readings WHERE id = ?",
                (body["id"],),
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["temperature_c"], 31.4)
        self.assertEqual(row["humidity_percent"], 72.1)
        self.assertEqual(row["gas_reading"], 1840)
        self.assertEqual(row["measured_at"], "2026-11-01T10:20:30Z")

    def test_missing_and_invalid_device_tokens_are_rejected(self) -> None:
        missing_status, _ = self.ingest(token=None)
        invalid_status, _ = self.ingest(token="wrong-device-token")

        self.assertEqual(missing_status, 401)
        self.assertEqual(invalid_status, 401)

    def test_missing_server_token_configuration_fails_closed(self) -> None:
        configured_token = os.environ.pop("SENSOR_DEVICE_TOKEN")
        try:
            status_code, body = self.ingest()
        finally:
            os.environ["SENSOR_DEVICE_TOKEN"] = configured_token

        self.assertEqual(status_code, 401)
        self.assertNotIn(configured_token, str(body))

    def test_invalid_sensor_values_return_422(self) -> None:
        invalid_payloads = (
            self.valid_payload(temperature=85.1),
            self.valid_payload(humidity=100.1),
            self.valid_payload(gas_reading=4096),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                status_code, _ = self.ingest(payload)
                self.assertEqual(status_code, 422)

    def test_duplicate_reading_id_returns_original_row_without_insert(self) -> None:
        first_status, first = self.ingest()
        repeated_status, repeated = self.ingest(
            self.valid_payload(temperature=32.0, gas_reading=1900)
        )

        self.assertEqual(first_status, 201)
        self.assertEqual(repeated_status, 200)
        self.assertEqual(repeated["id"], first["id"])

        with database_connection(self.database_path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM sensor_readings"
            ).fetchone()[0]
            temperature = connection.execute(
                "SELECT temperature_c FROM sensor_readings WHERE id = ?",
                (first["id"],),
            ).fetchone()[0]

        self.assertEqual(count, 1)
        self.assertEqual(temperature, 31.4)

    def test_same_values_with_different_reading_ids_are_distinct(self) -> None:
        first_status, first = self.ingest()
        second_status, second = self.ingest(
            self.valid_payload(reading_id="boot-uuid:1043")
        )

        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 201)
        self.assertNotEqual(first["id"], second["id"])

        with database_connection(self.database_path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM sensor_readings"
            ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_each_metric_independently_triggers_an_alert(self) -> None:
        cases = (
            ("temperature", 36.0, "temperature"),
            ("humidity", 81.0, "humidity"),
            ("gas_reading", 3001, "gas_proxy"),
        )
        for device_id, (field, value, expected_metric) in enumerate(cases, 1):
            with self.subTest(metric=expected_metric):
                status, body = self.ingest(
                    self.valid_payload(
                        device_id=f"sensor-{device_id}",
                        reading_id=f"sample-{device_id}",
                        **{field: value},
                    )
                )
                self.assertEqual(status, 201)
                self.assertEqual(
                    [alert["metric"] for alert in body["active_alerts"]],
                    [expected_metric],
                )

    def test_values_below_or_exactly_at_threshold_do_not_alert(self) -> None:
        below_status, below = self.ingest(
            self.valid_payload(
                device_id="sensor-below",
                temperature=34.9,
                humidity=79.9,
                gas_reading=2999,
            )
        )
        at_status, at = self.ingest(
            self.valid_payload(
                device_id="sensor-at",
                reading_id="sample-at-threshold",
                temperature=35.0,
                humidity=80.0,
                gas_reading=3000,
            )
        )

        self.assertEqual(below_status, 201)
        self.assertEqual(at_status, 201)
        self.assertEqual(below["active_alerts"], [])
        self.assertEqual(at["active_alerts"], [])
        with database_connection(self.database_path) as connection:
            alert_count = connection.execute(
                "SELECT COUNT(*) FROM sensor_alerts"
            ).fetchone()[0]
        self.assertEqual(alert_count, 0)

    def test_no_duplicate_alert_while_metric_remains_above_threshold(self) -> None:
        _, first = self.ingest(self.valid_payload(temperature=36.0))
        _, second = self.ingest(
            self.valid_payload(reading_id="boot-uuid:1043", temperature=40.0)
        )

        self.assertEqual(len(first["active_alerts"]), 1)
        self.assertEqual(len(second["active_alerts"]), 1)
        self.assertEqual(
            second["active_alerts"][0]["id"],
            first["active_alerts"][0]["id"],
        )
        with database_connection(self.database_path) as connection:
            alert_count = connection.execute(
                "SELECT COUNT(*) FROM sensor_alerts"
            ).fetchone()[0]
        self.assertEqual(alert_count, 1)

    def test_alert_clears_when_metric_returns_to_threshold(self) -> None:
        _, raised = self.ingest(self.valid_payload(temperature=36.0))
        _, normal = self.ingest(
            self.valid_payload(reading_id="boot-uuid:1043", temperature=35.0)
        )

        self.assertEqual(len(raised["active_alerts"]), 1)
        self.assertEqual(normal["active_alerts"], [])
        with database_connection(self.database_path) as connection:
            cleared_at = connection.execute(
                "SELECT cleared_at FROM sensor_alerts WHERE id = ?",
                (raised["active_alerts"][0]["id"],),
            ).fetchone()[0]
        self.assertIsNotNone(cleared_at)

    def test_crossing_again_after_clear_creates_a_new_alert_episode(self) -> None:
        _, first = self.ingest(self.valid_payload(temperature=36.0))
        self.ingest(
            self.valid_payload(reading_id="boot-uuid:1043", temperature=35.0)
        )
        _, second = self.ingest(
            self.valid_payload(reading_id="boot-uuid:1044", temperature=37.0)
        )

        self.assertEqual(len(second["active_alerts"]), 1)
        self.assertNotEqual(
            second["active_alerts"][0]["id"],
            first["active_alerts"][0]["id"],
        )
        with database_connection(self.database_path) as connection:
            alert_count = connection.execute(
                "SELECT COUNT(*) FROM sensor_alerts"
            ).fetchone()[0]
        self.assertEqual(alert_count, 2)

    def test_multiple_metrics_can_trigger_simultaneously(self) -> None:
        _, body = self.ingest(
            self.valid_payload(temperature=36.0, humidity=81.0, gas_reading=3001)
        )

        self.assertEqual(
            {alert["metric"] for alert in body["active_alerts"]},
            {"temperature", "humidity", "gas_proxy"},
        )

    def test_duplicate_reading_id_does_not_duplicate_or_reconcile_alerts(self) -> None:
        first_status, first = self.ingest(self.valid_payload(temperature=36.0))
        duplicate_status, duplicate = self.ingest(
            self.valid_payload(temperature=30.0, humidity=81.0)
        )

        self.assertEqual(first_status, 201)
        self.assertEqual(duplicate_status, 200)
        self.assertEqual(duplicate["id"], first["id"])
        self.assertEqual(
            [alert["metric"] for alert in duplicate["active_alerts"]],
            ["temperature"],
        )
        with database_connection(self.database_path) as connection:
            reading_count = connection.execute(
                "SELECT COUNT(*) FROM sensor_readings"
            ).fetchone()[0]
            alert_count = connection.execute(
                "SELECT COUNT(*) FROM sensor_alerts"
            ).fetchone()[0]
        self.assertEqual(reading_count, 1)
        self.assertEqual(alert_count, 1)

    def test_alert_failure_rolls_back_the_sensor_reading(self) -> None:
        with database_connection(self.database_path) as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_test_alert
                BEFORE INSERT ON sensor_alerts
                BEGIN
                    SELECT RAISE(ABORT, 'test alert failure');
                END
                """
            )

        with self.assertLogs("api.sensors", level="ERROR"):
            status_code, _ = self.ingest(self.valid_payload(temperature=36.0))

        self.assertEqual(status_code, 500)
        with database_connection(self.database_path) as connection:
            reading_count = connection.execute(
                "SELECT COUNT(*) FROM sensor_readings"
            ).fetchone()[0]
            alert_count = connection.execute(
                "SELECT COUNT(*) FROM sensor_alerts"
            ).fetchone()[0]
        self.assertEqual(reading_count, 0)
        self.assertEqual(alert_count, 0)

    def test_devices_have_independent_alert_episodes(self) -> None:
        _, first_device = self.ingest(
            self.valid_payload(device_id="sensor-one", temperature=36.0)
        )
        _, second_device = self.ingest(
            self.valid_payload(
                device_id="sensor-two",
                reading_id="other-device-1",
                temperature=37.0,
            )
        )
        _, first_cleared = self.ingest(
            self.valid_payload(
                device_id="sensor-one",
                reading_id="boot-uuid:1043",
                temperature=35.0,
            )
        )

        self.assertEqual(len(first_device["active_alerts"]), 1)
        self.assertEqual(len(second_device["active_alerts"]), 1)
        self.assertEqual(first_cleared["active_alerts"], [])
        self.assertEqual(second_device["active_alerts"][0]["device_id"], "sensor-two")

    def test_database_failure_returns_controlled_error(self) -> None:
        with self.assertLogs("api.sensors", level="ERROR"):
            with patch(
                "api.sensors.insert_sensor_reading",
                side_effect=sqlite3.OperationalError("private database detail"),
            ):
                status_code, body = self.ingest()

        self.assertEqual(status_code, 500)
        self.assertEqual(
            body["detail"], "The sensor reading could not be stored."
        )
        self.assertNotIn("private database detail", str(body))

    def test_router_is_registered_without_removing_existing_routes(self) -> None:
        paths = set(app.openapi()["paths"])

        self.assertIn("/api/sensors/readings", paths)
        self.assertIn("/api/predict", paths)
        self.assertIn("/api/model-info", paths)


if __name__ == "__main__":
    unittest.main()
