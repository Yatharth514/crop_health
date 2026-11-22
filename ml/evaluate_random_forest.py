import json
import time
from pathlib import Path

import joblib
import numpy as np

from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

from ml.config import CLASS_NAMES


ROOT = Path(__file__).resolve().parent.parent

MODEL_PATH = ROOT / "models" / "random_forest_tomato.joblib"

FEATURE_PATH = (
    ROOT / "data" / "features" / "test_features.npz"
)

RESULT_PATH = ROOT / "results" / "random_forest_test.json"


def main():

    print("Loading Random Forest model...")

    saved = joblib.load(MODEL_PATH)

    model = saved["model"]

    if tuple(saved["class_names"]) != CLASS_NAMES:
        raise ValueError("Class ordering mismatch")

    print("Loading test features...")

    data = np.load(FEATURE_PATH, allow_pickle=False)

    X_test = data["X"]
    y_test = data["y"]

    if X_test.shape[1] != saved["feature_count"]:
        raise ValueError("Feature dimension mismatch")

    print("Test samples:", len(X_test))

    start = time.perf_counter()

    predictions = model.predict(X_test)

    elapsed = time.perf_counter() - start

    accuracy = accuracy_score(y_test, predictions)

    macro_f1 = f1_score(
        y_test,
        predictions,
        labels=CLASS_NAMES,
        average="macro"
    )

    report = classification_report(
        y_test,
        predictions,
        labels=CLASS_NAMES,
        output_dict=True,
        zero_division=0
    )

    matrix = confusion_matrix(
        y_test,
        predictions,
        labels=CLASS_NAMES
    )

    print("\n========== RANDOM FOREST TEST RESULTS ==========")

    print("Accuracy:", accuracy)
    print("Macro F1:", macro_f1)

    print("\nClassification Report:")

    print(classification_report(
        y_test,
        predictions,
        labels=CLASS_NAMES,
        zero_division=0
    ))

    print("Confusion Matrix:")
    print(matrix)

    print("\nInference time:", elapsed, "seconds")
    print("Average time per image:", elapsed / len(X_test), "seconds")

    results = {
        "model": "RandomForestClassifier",
        "best_params": saved["best_params"],
        "test_samples": len(X_test),
        "accuracy": float(accuracy),
        "macro_f1": float(macro_f1),
        "classification_report": report,
        "confusion_matrix": matrix.tolist(),
        "inference_time_seconds": elapsed,
        "average_inference_time_seconds": elapsed / len(X_test),
    }

    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

    print("\nResults saved to:", RESULT_PATH)


if __name__ == "__main__":
    main()