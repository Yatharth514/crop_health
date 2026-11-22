# Crop Health Early Warning Node

This project is a prototype for tomato crop-health monitoring. It combines two independent tools in one web application: a Random Forest classifier for tomato leaf photos and an ESP32 node that reports environmental readings and threshold alerts.

The sensor readings do not affect the image classification. The potentiometer used in the simulation is an ADC proxy, not a gas sensor.

## What the project does

### Tomato leaf classification

- Accepts JPEG, PNG, or WebP images up to 10 MB.
- Classifies images as **healthy**, **early blight**, or **late blight**.
- Extracts 369 handcrafted color and texture features from each image and passes them to the trained Random Forest model.
- Shows the predicted class and tree-vote scores. These scores are not calibrated probabilities.

The current API loads `models/random_forest_tomato.joblib`. On the held-out test set of 920 images, the saved evaluation reports 93.48% accuracy and 92.82% macro F1. These results are from PlantVillage images and do not establish performance on field photographs.

### Environmental monitoring

The ESP32 firmware reads a DHT22 temperature and humidity sensor and a potentiometer connected to its ADC input. It smooths temperature and humidity with a five-reading moving average, evaluates demonstration thresholds, and controls an LED:

| Measurement | Threshold |
|---|---:|
| Temperature | > 35 °C |
| Humidity | > 80% |
| Simulated gas ADC proxy | > 3000 (range 0–4095) |

No thresholds exceeded means **NORMAL**; one means **WARNING**; two or more means **CRITICAL**. The LED is off, steady on, or blinking for those states respectively. FastAPI stores sensor readings and alert events in SQLite, and the React dashboard shows readings, history, status, and active alerts.

## Architecture

```text
Leaf photo → FastAPI feature extraction → Random Forest → classification result
                                                        ↘
                                                          React dashboard
                                                        ↗
ESP32 sensors → Wi-Fi / HTTP → FastAPI → SQLite → sensor readings and alerts
```

The two paths meet in the dashboard only. The system does not calculate a combined disease-risk score.

## Hardware and pins

| Component | Pin |
|---|---:|
| DHT22 | GPIO16 |
| Potentiometer (simulated ADC input) | GPIO34 |
| Status LED | GPIO2 |
| LCD SDA / SCL | GPIO21 / GPIO22 |

## Requirements

- Windows with Python 3.11 recommended
- Node.js and npm
- VS Code with the Wokwi extension and PlatformIO support
- A local development token shared between the firmware and backend

## Run the application

Use separate terminals for the backend and frontend. Start the backend before running the Wokwi simulation.

### 1. Install Python dependencies

From the project root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The checked-in Random Forest model is used for inference; you do not need to download or retrain the dataset to run the app.

### 2. Configure the device token and start FastAPI

Create `platformio-build/crop-node-firmware/include/secrets.h` locally:

```cpp
#define SENSOR_DEVICE_TOKEN "replace-with-a-local-development-token"
```

The file is ignored by Git. In the backend terminal, use the same token:

```powershell
$env:SENSOR_DEVICE_TOKEN = "replace-with-a-local-development-token"
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The firmware sends its readings to `http://host.wokwi.internal:8000/api/sensors/readings`. Binding FastAPI to `0.0.0.0` allows the VS Code private Wokwi gateway to reach the development server. Allow the connection through Windows Firewall if prompted, and use this setup on a trusted development network. Never commit a real token.

### 3. Start the React frontend

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL, usually `http://localhost:5173`. The frontend uses `http://127.0.0.1:8000` by default. Set `VITE_API_BASE_URL` before starting Vite if the backend uses another URL.

### 4. Build and start the Wokwi simulation

Open `platformio-build/crop-node-firmware` in VS Code. Build the `esp32dev` environment, then open `diagram.json` and start the Wokwi simulator. For a PlatformIO command-line build, run this from the firmware directory:

```powershell
pio run -e esp32dev
```

Use the **VS Code private IoT Gateway** for local backend access. The simulated ESP32 connects to `Wokwi-GUEST` and uses `host.wokwi.internal`; `localhost` and `127.0.0.1` inside the simulated firmware will not point to the host computer. The public Wokwi gateway cannot reach the host's local network. See the [Wokwi ESP32 Wi-Fi guide](https://docs.wokwi.com/guides/esp32-wifi) and [Wokwi for VS Code project configuration](https://docs.wokwi.com/vscode/project-config).

The firmware samples every 2 seconds and offers a reading for upload every 10 seconds. Its network work runs separately from sensor monitoring, so readings and LED behavior continue during Wi-Fi or backend failures. Check the Serial Monitor for connection messages, HTTP status codes, and request errors. A new reading normally returns HTTP 201; an idempotent retry can return HTTP 200.

## API endpoints

### Image classification

- `GET /` — service status
- `GET /health` — model readiness
- `GET /api/model-info` — model architecture, classes, feature count, and parameters
- `POST /api/predict` — classify an uploaded image using multipart field `image`

### Sensor monitoring

- `POST /api/sensors/readings` — authenticated sensor ingestion (`X-Device-Token` header)
- `GET /api/sensors/latest?device_id=wokwi-esp32-01`
- `GET /api/sensors/history?device_id=wokwi-esp32-01`
- `GET /api/sensors/alerts?device_id=wokwi-esp32-01`
- `GET /api/sensors/status?device_id=wokwi-esp32-01`

The ingestion payload uses `device_id`, `reading_id`, `temperature`, `humidity`, `gas_reading`, and optional timezone-aware `measured_at`. Repeated `(device_id, reading_id)` requests return the existing record instead of inserting another row.

Sensor data is stored in `data/sensor_monitoring.sqlite3` by default. Set `SENSOR_DATABASE_PATH` to use a different database location.

## Tests and build checks

From the project root:

```powershell
python -m unittest discover -s tests -p "test_sensor_*.py" -v
```

Run the complete test suite with:

```powershell
python -m unittest discover -s tests -v
```

The existing `tests/test_api.py` also contains two stale assertions: one expects a `device` field in model information, and another expects a fixed prediction for an image. These are unrelated to the sensor APIs. To check the frontend production build:

```powershell
cd frontend
npm run build
```

## Optional Random Forest training

To prepare data and train a new Random Forest model, run these commands from the project root:

```powershell
python -m ml.download_dataset
python -m ml.prepare_dataset
python -m ml.prepare_rf_features
python -m ml.train_random_forest
python -m ml.evaluate_random_forest
```

Training uses the training split; validation selects among the configured Random Forest experiments; the separate evaluation command reports performance on the test split. The trained model is saved to `models/random_forest_tomato.joblib`.

## Limitations

- The image classifier supports only three tomato classes and was evaluated on a curated dataset. Field performance may differ.
- The potentiometer simulates an ADC signal; it does not measure gas concentration.
- Sensor thresholds are demonstration settings, not validated agronomic disease thresholds.
- Sensor monitoring was developed and exercised with Wokwi; physical sensor calibration and field deployment remain future work.
- Image classification and environmental alerts are independent outputs.
