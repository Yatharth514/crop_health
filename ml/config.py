from pathlib import Path
import os
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("CROP_DATA_DIR", ROOT / "data"))
IMAGE_ROOT = Path(os.getenv("PLANTVILLAGE_IMAGE_ROOT", DATA_DIR / "plantvillage"))
MANIFEST_DIR = DATA_DIR / "manifests"
MODELS_DIR = Path(os.getenv("CROP_MODELS_DIR", ROOT / "models"))
RESULTS_DIR = ROOT / "results"
CHECKPOINT_PATH = Path(os.getenv("CROP_CHECKPOINT", MODELS_DIR / "mobilenet_v3_small_tomato.pt"))
DATASET_ID = "mohanty/PlantVillage"
DATASET_CONFIG = "default"
CLASS_NAMES = ("healthy", "early_blight", "late_blight")
SOURCE_CLASSES = {"Tomato___healthy": "healthy", "Tomato___Early_blight": "early_blight", "Tomato___Late_blight": "late_blight"}
DISPLAY_NAMES = {"healthy": "Healthy", "early_blight": "Early Blight", "late_blight": "Late Blight"}
INPUT_SIZE = 224
BATCH_SIZE = 32
SEED = 42
