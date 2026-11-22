from pathlib import Path
import io
import tempfile

import joblib
import numpy as np
from PIL import Image

from ml.config import CLASS_NAMES
from ml.feature_extraction import extract_features


ROOT = Path(__file__).resolve().parent.parent

MODEL_PATH = ROOT / "models" / "random_forest_tomato.joblib"


def extract_features_from_image(image):
    """
    Extract the same handcrafted features used during training.
    Uses a temporary PNG file.
    """

    temp_path = None

    try:
        # Create a temporary file and close it before reopening.
        with tempfile.NamedTemporaryFile(
            suffix=".png",
            delete=False
        ) as temp:
            temp_path = Path(temp.name)

        # Save the uploaded image.
        image = image.convert("RGB")
        image.save(temp_path, format="PNG")

        # Extract features using the existing feature extractor.
        features = extract_features(temp_path)

        return features

    finally:
        # Clean up the temporary image.
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

class RandomForestPredictor:

    def __init__(self, model_bundle):

        self.model = model_bundle["model"]
        self.class_names = tuple(model_bundle["class_names"])
        self.feature_count = int(model_bundle["feature_count"])
        self.best_params = model_bundle["best_params"]

        if self.class_names != tuple(CLASS_NAMES):
            raise ValueError(
                "Model class names do not match project configuration."
            )

        if self.feature_count != 369:
            raise ValueError(
                f"Expected 369 features, got {self.feature_count}."
            )

        self.classes = self.model.classes_

    def predict_features(self, features):
        """
        Generate disease prediction from extracted features.
        """

        features = np.asarray(
            features,
            dtype=np.float32
        ).reshape(1, -1)

        if features.shape[1] != self.feature_count:
            raise ValueError(
                f"Expected {self.feature_count} features, "
                f"received {features.shape[1]}."
            )

        prediction = self.model.predict(features)[0]

        probabilities = self.model.predict_proba(features)[0]

        predicted_class = str(prediction)

        scores = {
            str(class_name): float(probability)
            for class_name, probability in zip(
                self.classes,
                probabilities
            )
        }

        return {
            "predicted_class": predicted_class,

            "top_prediction_score": scores[predicted_class],

            "class_scores": scores,

            "score_note": (
                "Random Forest class scores are estimates based on "
                "tree voting and are not calibrated probabilities."
            ),

            "model": "Random Forest",

            "feature_count": self.feature_count
        }

    def predict_bytes(self, image_bytes):
        """
        Generate prediction directly from uploaded image bytes.
        """

        try:

            with Image.open(io.BytesIO(image_bytes)) as image:

                image = image.convert("RGB")

                features = extract_features_from_image(image)

        except Exception as exc:

            raise ValueError(
                "Unable to process the uploaded image."
            ) from exc

        return self.predict_features(features)


def load_rf_predictor():
    """
    Load the trained Random Forest model.
    """

    if not MODEL_PATH.exists():

        raise FileNotFoundError(
            f"Random Forest model not found: {MODEL_PATH}"
        )

    model_bundle = joblib.load(MODEL_PATH)

    return RandomForestPredictor(model_bundle)