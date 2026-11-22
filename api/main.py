"""Crop Health prediction service."""

import asyncio
import io
import logging
import os

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from PIL import Image, UnidentifiedImageError

from ml.config import CLASS_NAMES
from ml.rf_inference import load_rf_predictor
from api.sensor_store import initialize_database
from api.sensors import router as sensors_router


logger = logging.getLogger(__name__)


MAX_UPLOAD_BYTES = int(
    os.getenv("MAX_UPLOAD_BYTES", 10 * 1024 * 1024)
)

ALLOWED = {
    "image/jpeg",
    "image/png",
    "image/webp"
}


@asynccontextmanager
async def lifespan(app: FastAPI):

    app.state.predictor = None
    app.state.model_error = None
    app.state.sensor_store_ready = False
    app.state.sensor_store_error = None

    try:
        app.state.predictor = load_rf_predictor()
        print("Random Forest model loaded successfully.")

    except Exception as exc:
        app.state.model_error = str(exc)
        print("Model loading failed:", exc)

    try:
        initialize_database()
        app.state.sensor_store_ready = True
        logger.info("Sensor monitoring database initialized.")

    except Exception as exc:
        app.state.sensor_store_error = str(exc)
        logger.exception(
            "Sensor database initialization failed; sensor ingestion is disabled."
        )

    yield


app = FastAPI(
    title="Crop Health AI API",
    lifespan=lifespan
)

app.include_router(sensors_router)


app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173"
    ).split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)


@app.get("/")
def root():

    return {
        "service": "Crop Health AI",
        "status": "running"
    }


@app.get("/health")
def health(request: Request):

    ready = request.app.state.predictor is not None

    return {
        "status": "ok" if ready else "model_unavailable",
        "model_loaded": ready
    }


@app.get("/api/model-info")
def model_info(request: Request):

    predictor = request.app.state.predictor

    return {
        "architecture": "Random Forest",
        "supported_classes": list(CLASS_NAMES),
        "model_available": predictor is not None,
        "feature_count": (
            predictor.feature_count if predictor else None
        ),
        "parameters": (
            predictor.best_params if predictor else None
        )
    }


@app.post("/api/predict")
async def predict(
    request: Request,
    image: UploadFile = File(...)
):

    if image.content_type not in ALLOWED:

        raise HTTPException(
            status_code=415,
            detail="Upload a JPEG, PNG, or WebP image."
        )

    data = await image.read(MAX_UPLOAD_BYTES + 1)

    if len(data) > MAX_UPLOAD_BYTES:

        raise HTTPException(
            status_code=413,
            detail=(
                f"Image exceeds the "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit."
            )
        )

    try:

        with Image.open(io.BytesIO(data)) as decoded:
            decoded.verify()

    except (
        OSError,
        UnidentifiedImageError,
        ValueError,
        Image.DecompressionBombError
    ) as exc:

        raise HTTPException(
            status_code=400,
            detail="Image contents could not be decoded."
        ) from exc

    predictor = request.app.state.predictor

    if predictor is None:

        raise HTTPException(
            status_code=503,
            detail="The trained Random Forest model is unavailable."
        )

    try:

        result = await asyncio.to_thread(
            predictor.predict_bytes,
            data
        )

        return result

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc

    except Exception as exc:

        print("Prediction error:", repr(exc))

        raise HTTPException(
            status_code=500,
            detail="Prediction failed. Please retry with another image."
        ) from exc
