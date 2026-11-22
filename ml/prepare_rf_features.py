import argparse
from pathlib import Path

import numpy as np

from ml.dataset import ManifestDataset
from ml.feature_extraction import extract_features
from ml.config import CLASS_NAMES


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "features"


def prepare_split(split, force=False):

    manifest = PROJECT_ROOT / "data" / "manifests" / f"{split}.csv"

    output = OUTPUT_DIR / f"{split}_features.npz"

    if output.exists() and not force:
        raise FileExistsError(
            f"{output} already exists. "
            "Use --force only if you intentionally want to replace it."
        )

    dataset = ManifestDataset(manifest)

    features = []
    labels = []
    paths = []

    print(f"\nProcessing {split}: {len(dataset)} images")

    for i, row in enumerate(dataset.rows):

        image_path = dataset.resolve_image_path(row)

        x = extract_features(image_path)

        features.append(x)
        labels.append(row["label"])
        paths.append(str(image_path))

        if (i + 1) % 100 == 0:
            print(f"Processed {i + 1}/{len(dataset)}")

    X = np.stack(features)
    y = np.asarray(labels)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    np.savez_compressed(
        output,
        X=X,
        y=y,
        paths=np.asarray(paths),
        class_names=np.asarray(CLASS_NAMES)
    )

    print(f"\nSaved: {output}")
    print("Feature matrix:", X.shape)
    print("Labels:", y.shape)


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing feature cache files."
    )

    args = parser.parse_args()

    for split in ("train", "validation", "test"):
        prepare_split(split, force=args.force)


if __name__ == "__main__":
    main()