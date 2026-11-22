import json
from collections import Counter
from .dataset_source import load_source,parse_color_record
from .config import DATASET_ID,DATASET_CONFIG
def inspect(cache_dir=None):
    ds=load_source(cache_dir); result={"dataset":DATASET_ID,"config":DATASET_CONFIG,"splits":{}}
    for split in ("train","test"):
        part=ds[split]
        labels=Counter()
        for row in part:
            parsed=parse_color_record(row,split)
            if parsed: labels[parsed["label"]]+=1
        result["splits"][split]={"rows":len(part),"features":list(part.features),"color_tomato_counts":dict(labels)}
    return result
if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("--cache-dir"); a=p.parse_args()
    print(json.dumps(inspect(a.cache_dir),indent=2))