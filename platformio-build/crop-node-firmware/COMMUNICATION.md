# ESP32 to FastAPI communication

The firmware posts readings to the existing `POST /api/sensors/readings`
endpoint. Its JSON uses the backend schema exactly: `device_id`, `reading_id`,
`temperature`, `humidity`, `gas_reading`, and (when the clock is synchronized)
`measured_at`. The simulated gas reading remains a proxy value; it is not a gas
concentration.

## Configure the device token locally

Create `include/secrets.h` (this path is ignored by Git) with the same token
configured for the backend:

```cpp
#define SENSOR_DEVICE_TOKEN "your-local-development-token"
```

The firmware never prints the token. If this local header is absent or the
macro is empty, it continues sensor monitoring and reports that authenticated
uploads are skipped. Do not commit `include/secrets.h` or put the token in
`platformio.ini`, `wokwi.toml`, or source control.

In the PowerShell terminal used to run FastAPI, configure the matching token
and start the server on an address reachable through the private gateway:

```powershell
$env:SENSOR_DEVICE_TOKEN = "your-local-development-token"
..\.venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Allow the local Wokwi gateway to reach TCP port 8000 through Windows Firewall
if prompted. Keep the service on a trusted development network.

## Wokwi VS Code networking

Wokwi for VS Code includes its private IoT Gateway. Run the simulation from VS
Code with the gateway enabled; the firmware joins `Wokwi-GUEST` on channel 6
and uses `host.wokwi.internal` to reach the host FastAPI process. The default
URL is:

```text
http://host.wokwi.internal:8000/api/sensors/readings
```

To use another host or port, override `SENSOR_API_URL` as a PlatformIO build
macro or edit its default in `src/main.cpp`. Do not use `localhost` or
`127.0.0.1` in the simulated ESP32 URL. The public Wokwi gateway cannot access
the host's local network; use the VS Code private gateway for this local
backend workflow.

## Behavior and verification

Sensors are sampled every 2 seconds and a snapshot is offered for upload every
10 seconds. A separate FreeRTOS task handles Wi-Fi and HTTP with bounded
timeouts, so communication failures do not block sensor reads, LCD updates,
risk classification, or LED behavior. The queue keeps only the newest waiting
sample. A failed HTTP request is retried with the same `reading_id`, allowing
the backend's existing idempotency handling to prevent duplicate rows. When
NTP time is available, `measured_at` is sent in UTC; otherwise it is omitted
because that field is optional.

After building and starting the simulation, check Serial Monitor for Wi-Fi
state, POST attempts, HTTP status codes, response bodies, and transport errors.
The backend returns `201` for a new reading and `200` for an idempotent retry.
Verify persistence through the existing endpoints:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/sensors/latest?device_id=wokwi-esp32-01"
Invoke-RestMethod "http://127.0.0.1:8000/api/sensors/history?device_id=wokwi-esp32-01"
```

Stop FastAPI temporarily to confirm sensor monitoring continues while Serial
reports transport failures, then restart it and confirm uploads recover.
