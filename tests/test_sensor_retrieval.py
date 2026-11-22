"""HTTP tests for sensor reading, alert, and device-status retrieval."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app


class SensorRetrievalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "retrieval-test.sqlite3"
        self.environment = patch.dict(
            os.environ,
            {
                "SENSOR_DATABASE_PATH": str(self.database_path),
                "SENSOR_DEVICE_TOKEN": "temporary-retrieval-test-token",
            },
        )
        self.environment.start()
        self.model_loader = patch("api.main.load_rf_predictor", return_value=object())
        self.model_loader.start()
        self.client = TestClient(app)
        self.client.__enter__()
        self.reading_number = 0

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.model_loader.stop()
        self.environment.stop()
        self.temp_dir.cleanup()

    def post_reading(
        self,
        device_id: str = "sensor-one",
        *,
        reading_id: str | None = None,
        temperature: float = 22.0,
        humidity: float = 55.0,
        gas_reading: int = 1000,
    ) -> dict[str, object]:
        self.reading_number += 1
        payload = {
            "device_id": device_id,
            "reading_id": reading_id or f"retrieval:{self.reading_number}",
            "temperature": temperature,
            "humidity": humidity,
            "gas_reading": gas_reading,
            "measured_at": "2026-11-01T10:20:30Z",
        }
        response = self.client.post(
            "/api/sensors/readings",
            json=payload,
            headers={"X-Device-Token": "temporary-retrieval-test-token"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_latest_reading_for_a_device(self) -> None:
        self.post_reading(temperature=21.0)
        newest = self.post_reading(temperature=24.0)

        response = self.client.get(
            "/api/sensors/latest", params={"device_id": "sensor-one"}
        )

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["device_id"], "sensor-one")
        self.assertEqual(items[0]["latest_reading"]["id"], newest["id"])
        self.assertEqual(items[0]["latest_reading"]["temperature_c"], 24.0)

    def test_latest_reading_for_each_device(self) -> None:
        self.post_reading("sensor-one", temperature=20.0)
        latest_one = self.post_reading("sensor-one", temperature=23.0)
        self.post_reading("sensor-two", temperature=30.0)
        latest_two = self.post_reading("sensor-two", temperature=32.0)

        response = self.client.get("/api/sensors/latest")

        self.assertEqual(response.status_code, 200)
        items = {item["device_id"]: item["latest_reading"] for item in response.json()["items"]}
        self.assertEqual(items["sensor-one"]["id"], latest_one["id"])
        self.assertEqual(items["sensor-two"]["id"], latest_two["id"])

    def test_empty_database_and_explicit_unknown_device(self) -> None:
        latest = self.client.get("/api/sensors/latest")
        history = self.client.get(
            "/api/sensors/history", params={"device_id": "not-seen"}
        )
        alerts = self.client.get("/api/sensors/alerts")
        status = self.client.get("/api/sensors/status")
        unknown_latest = self.client.get(
            "/api/sensors/latest", params={"device_id": "not-seen"}
        )
        unknown_status = self.client.get(
            "/api/sensors/status", params={"device_id": "not-seen"}
        )

        self.assertEqual(latest.json(), {"items": []})
        self.assertEqual(history.json()["items"], [])
        self.assertEqual(history.json()["total"], 0)
        self.assertEqual(alerts.json()["items"], [])
        self.assertEqual(alerts.json()["total"], 0)
        self.assertEqual(status.json(), {"items": []})
        self.assertEqual(unknown_latest.json()["items"][0]["latest_reading"], None)
        self.assertEqual(unknown_status.json()["items"][0]["latest_reading"], None)
        self.assertIsNone(unknown_status.json()["items"][0]["last_received_at"])
        self.assertEqual(unknown_status.json()["items"][0]["active_alerts"], [])

    def test_history_newest_first_pagination_and_device_filter(self) -> None:
        first = self.post_reading("sensor-one", temperature=20.0)
        second = self.post_reading("sensor-one", temperature=21.0)
        third = self.post_reading("sensor-one", temperature=22.0)
        self.post_reading("sensor-two", temperature=40.0)

        response = self.client.get(
            "/api/sensors/history",
            params={"device_id": "sensor-one", "limit": 2, "offset": 1},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["limit"], 2)
        self.assertEqual(body["offset"], 1)
        self.assertEqual(
            [item["id"] for item in body["items"]],
            [second["id"], first["id"]],
        )
        self.assertNotEqual(body["items"][0]["id"], third["id"])
        self.assertTrue(all(item["device_id"] == "sensor-one" for item in body["items"]))

    def test_alerts_include_active_and_cleared_entries_and_filter_by_device(self) -> None:
        self.post_reading("sensor-one", temperature=36.0)
        self.post_reading("sensor-one", temperature=35.0)
        active = self.post_reading("sensor-one", temperature=37.0)
        self.post_reading("sensor-two", humidity=81.0)

        all_alerts = self.client.get(
            "/api/sensors/alerts", params={"device_id": "sensor-one"}
        ).json()
        active_alerts = self.client.get(
            "/api/sensors/alerts",
            params={"device_id": "sensor-one", "active_only": "true"},
        ).json()

        self.assertEqual(all_alerts["total"], 2)
        self.assertEqual(len(all_alerts["items"]), 2)
        self.assertIsNotNone(all_alerts["items"][1]["cleared_at"])
        self.assertIsNone(all_alerts["items"][0]["cleared_at"])
        self.assertEqual(active_alerts["total"], 1)
        self.assertEqual(active_alerts["items"][0]["reading_id"], active["id"])

    def test_alert_pagination_is_newest_first(self) -> None:
        first = self.post_reading(temperature=36.0)
        self.post_reading(temperature=35.0)
        second = self.post_reading(temperature=37.0)
        self.post_reading(temperature=35.0)
        third = self.post_reading(temperature=38.0)

        response = self.client.get(
            "/api/sensors/alerts", params={"limit": 2, "offset": 1}
        )

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["total"], 3)
        self.assertEqual(
            [item["reading_id"] for item in body["items"]],
            [second["id"], first["id"]],
        )
        self.assertNotEqual(body["items"][0]["reading_id"], third["id"])

    def test_status_returns_latest_last_seen_and_active_alerts(self) -> None:
        self.post_reading("sensor-one", temperature=36.0)
        newest = self.post_reading(
            "sensor-one", reading_id="status-newest", temperature=37.0
        )
        self.post_reading("sensor-two", temperature=24.0)

        one_status = self.client.get(
            "/api/sensors/status", params={"device_id": "sensor-one"}
        ).json()["items"][0]
        all_status = self.client.get("/api/sensors/status").json()["items"]

        self.assertEqual(one_status["latest_reading"]["id"], newest["id"])
        self.assertEqual(
            one_status["last_received_at"],
            one_status["latest_reading"]["received_at"],
        )
        self.assertEqual(len(one_status["active_alerts"]), 1)
        self.assertEqual({item["device_id"] for item in all_status}, {"sensor-one", "sensor-two"})
        self.assertTrue(all("online" not in item and "is_online" not in item for item in all_status))

    def test_status_for_a_device_without_readings_is_last_seen_unknown(self) -> None:
        response = self.client.get(
            "/api/sensors/status", params={"device_id": "not-seen"}
        )

        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        self.assertEqual(item["device_id"], "not-seen")
        self.assertIsNone(item["latest_reading"])
        self.assertIsNone(item["last_received_at"])
        self.assertEqual(item["active_alerts"], [])

    def test_invalid_pagination_parameters_return_422(self) -> None:
        requests = (
            ("/api/sensors/history", {"device_id": "sensor-one", "limit": 0}),
            ("/api/sensors/history", {"device_id": "sensor-one", "limit": 101}),
            ("/api/sensors/history", {"device_id": "sensor-one", "offset": -1}),
            ("/api/sensors/history", {"limit": 20}),
            ("/api/sensors/alerts", {"limit": 0}),
            ("/api/sensors/alerts", {"limit": 101}),
            ("/api/sensors/alerts", {"offset": -1}),
        )
        for path, params in requests:
            with self.subTest(path=path, params=params):
                response = self.client.get(path, params=params)
                self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
