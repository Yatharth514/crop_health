import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    classification_report,
)

from ml.config import CLASS_NAMES


ROOT = Path(__file__).resolve().parent.parent

FEATURE_DIR = ROOT / "data" / "features"
MODEL_DIR = ROOT / "models"
RESULT_DIR = ROOT / "results"


def load_features(split):

    data = np.load(
        FEATURE_DIR / f"{split}_features.npz",
        allow_pickle=False
    )

    return data["X"], data["y"]


def main():

    X_train, y_train = load_features("train")
    X_val, y_val = load_features("validation")

    experiments = [
        {"n_estimators": 100, "max_depth": 10, "min_samples_split": 2},
        {"n_estimators": 200, "max_depth": 20, "min_samples_split": 2},
        {"n_estimators": 300, "max_depth": None, "min_samples_split": 2},
        {"n_estimators": 300, "max_depth": 20, "min_samples_split": 5},
    ]

    best_model = None
    best_score = -1
    best_params = None

    results = []

    print("Training Random Forest experiments...")
    print("Training samples:", len(X_train))
    print("Validation samples:", len(X_val))

    for index, params in enumerate(experiments, start=1):

        print(f"\nExperiment RF-{index}")
        print("Parameters:", params)

        model = RandomForestClassifier(
            **params,
            random_state=42,
            n_jobs=-1,
            class_weight="balanced"
        )

        model.fit(X_train, y_train)

        predictions = model.predict(X_val)

        accuracy = accuracy_score(y_val, predictions)

        macro_f1 = f1_score(
            y_val,
            predictions,
            labels=CLASS_NAMES,
            average="macro"
        )

        print("Validation accuracy:", accuracy)
        print("Validation macro F1:", macro_f1)

        results.append({
            "experiment": f"RF-{index}",
            "parameters": params,
            "validation_accuracy": float(accuracy),
            "validation_macro_f1": float(macro_f1),
        })

        if macro_f1 > best_score:

            best_score = macro_f1
            best_model = model
            best_params = params

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    import joblib

    joblib.dump(
        {
            "model": best_model,
            "class_names": CLASS_NAMES,
            "feature_count": X_train.shape[1],
            "best_params": best_params,
        },
        MODEL_DIR / "random_forest_tomato.joblib"
    )

    with open(
        RESULT_DIR / "random_forest_validation.json",
        "w",
        encoding="utf-8"
    ) as f:

        json.dump({
            "best_params": best_params,
            "best_validation_macro_f1": best_score,
            "experiments": results,
        }, f, indent=4)

    print("\n========== BEST MODEL ==========")
    print("Parameters:", best_params)
    print("Validation macro F1:", best_score)

    print("\nClassification report:")
    print(classification_report(
        y_val,
        best_model.predict(X_val),
        labels=CLASS_NAMES
    ))

    print("\nSaved model:", MODEL_DIR / "random_forest_tomato.joblib")


if __name__ == "__main__":
    main()