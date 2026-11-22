"""Reuse and extract the Hugging Face PlantVillage image archive."""
import argparse,os,zipfile
from pathlib import Path
from .config import IMAGE_ROOT,DATASET_ID
def ensure_image_archive(cache_dir=None):
    if (IMAGE_ROOT/"raw"/"color").is_dir() or (IMAGE_ROOT/"color").is_dir(): return IMAGE_ROOT
    roots=[Path(cache_dir)] if cache_dir else []
    roots.append(Path(os.getenv("HF_HOME",Path.home()/".cache"/"huggingface"))/"hub"/"datasets--mohanty--PlantVillage"/"snapshots")
    candidates=[]
    for root in roots:
        if root.exists(): candidates.extend(root.rglob("data.zip"))
    if not candidates:
        try:
            from huggingface_hub import hf_hub_download
            candidates=[Path(hf_hub_download(DATASET_ID,"data.zip",repo_type="dataset",cache_dir=cache_dir))]
        except Exception as exc: raise RuntimeError("PlantVillage data.zip is absent from cache and could not be fetched.") from exc
    archive=candidates[0]; IMAGE_ROOT.mkdir(parents=True,exist_ok=True); base=IMAGE_ROOT.resolve()
    with zipfile.ZipFile(archive) as zf:
        for item in zf.infolist():
            out=(IMAGE_ROOT/item.filename).resolve()
            if out!=base and base not in out.parents: raise ValueError("Unsafe path in dataset archive")
        zf.extractall(IMAGE_ROOT)
    return IMAGE_ROOT
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--cache-dir"); args=parser.parse_args()
    from .dataset_source import load_source,selected_records
    ds=load_source(args.cache_dir); selected=selected_records(ds)
    ensure_image_archive(args.cache_dir)
    print(f"HF config default; schema field text (string path). Official rows train={len(ds['train'])}, test={len(ds['test'])}.")
    print(f"Selected color tomato paths: train={len(selected['train'])}, test={len(selected['test'])}. Archive extracted under {IMAGE_ROOT}.")
if __name__=="__main__": main()