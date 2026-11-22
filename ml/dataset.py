
from pathlib import Path
import csv

from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms

from .config import INPUT_SIZE, CLASS_NAMES


# Project root: parent directory of the ml package
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_ROOT = PROJECT_ROOT / "data" / "plantvillage"


NORMALIZE = transforms.Normalize(
    (0.485, 0.456, 0.406),
    (0.229, 0.224, 0.225)
)


def transform(train=False):
    ops = [transforms.Resize((INPUT_SIZE, INPUT_SIZE))]

    if train:
        ops += [
            transforms.RandomHorizontalFlip(),
            transforms.RandomRotation(12),
            transforms.ColorJitter(
                brightness=0.15,
                contrast=0.15,
                saturation=0.15
            )
        ]

    return transforms.Compose(
        ops + [transforms.ToTensor(), NORMALIZE]
    )


class ManifestDataset(Dataset):

    def __init__(self, manifest, train=False):

        with Path(manifest).open(
            newline="",
            encoding="utf-8"
        ) as f:
            self.rows = list(csv.DictReader(f))

        self.tx = transform(train)

        self.mapping = {
            c: i for i, c in enumerate(CLASS_NAMES)
        }

        if any(
            r["label"] not in self.mapping
            for r in self.rows
        ):
            raise ValueError(
                "Manifest has unsupported class labels"
            )

    def __len__(self):
        return len(self.rows)

    def resolve_image_path(self, row):

        # First try the existing absolute path.
        image_path = Path(row["image_path"])

        if image_path.exists():
            return image_path

        # Fall back to the portable relative source_path.
        source_path = row.get("source_path")

        if source_path:
            image_path = DATA_ROOT / source_path

            if image_path.exists():
                return image_path

        raise FileNotFoundError(
            f"Image not found.\n"
            f"Original path: {row['image_path']}\n"
            f"Relative path: {source_path}"
        )

    def __getitem__(self, i):

        row = self.rows[i]

        image_path = self.resolve_image_path(row)

        with Image.open(image_path) as im:
            image = im.convert("RGB")

        return self.tx(image), self.mapping[row["label"]]

