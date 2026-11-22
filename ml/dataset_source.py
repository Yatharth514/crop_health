"""Access actual PlantVillage path-manifest data."""
from pathlib import Path
from .config import DATASET_ID,DATASET_CONFIG,IMAGE_ROOT,SOURCE_CLASSES
def parse_color_record(record,split):
    if "text" not in record or not isinstance(record["text"],str): raise ValueError(f"Expected source field text; got {list(record)}")
    raw=record["text"].replace("\\","/"); parts=raw.split("/")
    if "color" not in parts: return None
    i=parts.index("color")
    if len(parts)<=i+1: return None
    source_label=parts[i+1]
    if source_label not in SOURCE_CLASSES: return None
    rel=Path(*(parts[parts.index("raw"):] if "raw" in parts else parts[i:]))
    return {"split":split,"source_label":source_label,"label":SOURCE_CLASSES[source_label],"source_path":raw,"image_path":str(IMAGE_ROOT/rel)}
def load_source(cache_dir=None):
    try: from datasets import load_dataset
    except ImportError as exc: raise RuntimeError("Install requirements before loading PlantVillage.") from exc
    return load_dataset(DATASET_ID,DATASET_CONFIG,cache_dir=cache_dir)
def selected_records(dataset):
    result={"train":[],"test":[]}
    for split in result:
        if split not in dataset: raise ValueError(f"Official split missing: {split}")
        for row in dataset[split]:
            parsed=parse_color_record(row,split)
            if parsed: result[split].append(parsed)
    return result