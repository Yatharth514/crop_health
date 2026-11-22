from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

from ml.config import CLASS_NAMES
from ml.dataset import ManifestDataset
from ml.inference import load_predictor


def main():
    dataset = ManifestDataset("data/manifests/test.csv")
    predictor = load_predictor(device="cuda")

    y_true = []
    y_pred = []

    print(f"Evaluating {len(dataset)} images...")
    print(f"Device: {predictor.device}")

    for index, row in enumerate(dataset.rows):
        image_path = dataset.resolve_image_path(row)
        result = predictor.predict_bytes(image_path.read_bytes())

        y_true.append(row["label"])
        y_pred.append(result["predicted_class"])

        if (index + 1) % 100 == 0:
            print(f"Processed {index + 1}/{len(dataset)}")

    print("\n========== RESULTS ==========")

    print("Accuracy:", accuracy_score(y_true, y_pred))

    print("Macro F1:", f1_score(
        y_true,
        y_pred,
        labels=CLASS_NAMES,
        average="macro"
    ))

    print("\nClassification Report:")
    print(classification_report(
        y_true,
        y_pred,
        labels=CLASS_NAMES,
        zero_division=0
    ))

    print("Confusion Matrix:")
    print(confusion_matrix(
        y_true,
        y_pred,
        labels=CLASS_NAMES
    ))


if __name__ == "__main__":
    main()