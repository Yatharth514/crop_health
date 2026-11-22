# Crop Health Early Warning Node

Reconstruction of the three-class tomato leaf classifier and upload web app. Internal class order: healthy, early_blight, late_blight. Architecture: MobileNetV3 Small. Returned softmax outputs are model scores, not calibrated probabilities.

## Recovery findings

The former project directory and its Git history were missing. The Hugging Face cache contains the mohanty/PlantVillage default configuration, Arrow manifests with 129,783 train and 33,133 test rows, and a single text string-path feature. These records include color, grayscale, and segmented variants. This pipeline selects only the color paths belonging to the three requested tomato classes. A data.zip archive is cached locally (2,184,723,441 bytes). No trained project checkpoint was found. The archive has not been extracted and processed in this session, so prepared counts, duplicate totals, metrics, and real predictions are not yet known.

No leaf-group identifiers appear in the source schema. The preparation code does not create fake leaf IDs. It hashes original image bytes, removes train copies also found in official test, and draws validation from the remaining official training images only. It preserves the official test manifest.

## Setup on Windows PowerShell

Run from this project directory:

    py -3.11 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt

Install the PyTorch/torchvision wheel matching your desired CUDA configuration if needed. CPU inference is supported.

## Prepare, train, evaluate

    python -m ml.download_dataset
    python -m ml.prepare_dataset
    python -m ml.train
    python -m ml.evaluate

The cached HF archive is reused and extracted under data/plantvillage. CSV manifests and preparation_report.json are written under data/manifests. The checkpoint is models/mobilenet_v3_small_tomato.pt. Evaluation JSON and confusion-matrix image are in results/. Training uses only train and validation; the test partition is evaluated by the separate evaluation command.

## Run the web application

Backend:

    python -m uvicorn api.main:app --host 127.0.0.1 --port 8000

Frontend in a second terminal:

    cd frontend
    npm install
    npm run dev

Open http://localhost:5173. The frontend uses http://127.0.0.1:8000 by default; override with VITE_API_BASE_URL. The API provides GET /, GET /health, GET /api/model-info, and POST /api/predict with multipart field image. Supported uploads are JPEG, PNG, and WebP, limited to 10 MiB.

## Checks

    python -m unittest discover -s tests -v
    cd frontend
    npm run build

The dataset unit tests do not fetch the archive. Backend real-model prediction requires installed model dependencies and a trained checkpoint. No mocked check is evidence of model accuracy.

## Sensor reading ingestion

The backend creates its SQLite sensor database at `data/sensor_monitoring.sqlite3` when it starts. Override the location with `SENSOR_DATABASE_PATH` if needed. Sensor ingestion requires a shared device token; set `SENSOR_DEVICE_TOKEN` in the backend terminal before starting FastAPI. For a local PowerShell session, use a temporary development value:

    $env:SENSOR_DEVICE_TOKEN = "replace-with-a-local-development-token"
    python -m uvicorn api.main:app --host 127.0.0.1 --port 8000

Send readings as JSON to `POST /api/sensors/readings` with the token in the `X-Device-Token` header. Do not commit real tokens or place them in frontend code. A new reading returns HTTP 201; resubmitting the same `device_id` and `reading_id` returns the original stored reading with HTTP 200. Sensor readings and environmental warnings are separate from image-based disease classifications.
