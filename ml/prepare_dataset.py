import csv,hashlib,json,random
from collections import Counter
from pathlib import Path
from PIL import Image,UnidentifiedImageError
from .config import MANIFEST_DIR,SEED,CLASS_NAMES
from .dataset_source import load_source,selected_records
from .download_dataset import ensure_image_archive
def sha256_file(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()
def validate_rgb(path):
    with Image.open(path) as im: im.verify()
    with Image.open(path) as im: return im.convert("RGB").size
def exclude_train_test_duplicates(train_rows,test_rows):
    test_hashes={r["sha256"] for r in test_rows}
    duplicates=[r for r in train_rows if r["sha256"] in test_hashes]
    return [r for r in train_rows if r["sha256"] not in test_hashes],duplicates
def missing_target_classes(rows):
    present={r["label"] for r in rows}
    return sorted(set(CLASS_NAMES)-present)
def prepare(cache_dir=None,validation_fraction=.15):
    ensure_image_archive(cache_dir)
    splits=selected_records(load_source(cache_dir))
    for split in ("train","test"):
        absent=missing_target_classes(splits[split])
        if absent: raise RuntimeError(f"Source {split} is missing target classes: {absent}")
    missing=[]; corrupt=[]; valid={k:[] for k in splits}
    for split,rows in splits.items():
        for row in rows:
            path=Path(row["image_path"])
            if not path.is_file(): missing.append({**row,"reason":"missing"}); continue
            try:
                validate_rgb(path); valid[split].append({**row,"sha256":sha256_file(path)})
            except (OSError,UnidentifiedImageError,ValueError,Image.DecompressionBombError) as exc: corrupt.append({**row,"reason":str(exc)})
    train,duplicates=exclude_train_test_duplicates(valid["train"],valid["test"])
    random.Random(SEED).shuffle(train)
    count=max(1,round(len(train)*validation_fraction)) if train else 0
    validation,train=train[:count],train[count:]
    MANIFEST_DIR.mkdir(parents=True,exist_ok=True)
    for name,rows in (("train",train),("validation",validation),("test",valid["test"])):
        with (MANIFEST_DIR/f"{name}.csv").open("w",newline="",encoding="utf-8") as f:
            fields=["image_path","label","source_label","source_path","split","sha256"]
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    report={"dataset_id":"mohanty/PlantVillage","config":"default","schema":{"text":"string path"},
      "source_color_rows":{k:len(v) for k,v in splits.items()},"valid_color_images":{k:len(v) for k,v in valid.items()},
      "final_counts":{"train":len(train),"validation":len(validation),"test":len(valid["test"])},
      "duplicate_groups_found":len({r["sha256"] for r in duplicates}),"duplicates_found":len(duplicates),"training_duplicates_excluded":len(duplicates),
      "missing_count":len(missing),"corrupt_count":len(corrupt),
      "class_counts":{name:dict(Counter(r["label"] for r in rows)) for name,rows in (("train",train),("validation",validation),("test",valid["test"]))},
      "excluded_duplicate_rows":duplicates,"missing":missing,"corrupt":corrupt}
    (MANIFEST_DIR/"preparation_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report
if __name__=="__main__":
    import argparse,json
    p=argparse.ArgumentParser(); p.add_argument("--cache-dir"); a=p.parse_args(); print(json.dumps(prepare(a.cache_dir),indent=2))