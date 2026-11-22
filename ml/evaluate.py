import json
import matplotlib.pyplot as plt
import numpy as np
import torch
from torch.utils.data import DataLoader
from sklearn.metrics import accuracy_score,precision_recall_fscore_support,confusion_matrix
from .config import CLASS_NAMES,MANIFEST_DIR,RESULTS_DIR,CHECKPOINT_PATH
from .dataset import ManifestDataset
from .inference import load_predictor
def main():
    predictor=load_predictor()
    loader=DataLoader(ManifestDataset(MANIFEST_DIR/"test.csv"),batch_size=32,shuffle=False,num_workers=0)
    true=[]; pred=[]
    with torch.inference_mode():
        for x,y in loader:
            pred.extend(predictor.model(x.to(predictor.device)).argmax(1).cpu().tolist()); true.extend(y.tolist())
    p,r,f,_=precision_recall_fscore_support(true,pred,labels=range(3),zero_division=0)
    cm=confusion_matrix(true,pred,labels=range(3))
    result={"checkpoint":str(CHECKPOINT_PATH),"samples":len(true),"accuracy":float(accuracy_score(true,pred)),
      "macro_precision":float(p.mean()),"macro_recall":float(r.mean()),"macro_f1":float(f.mean()),
      "class_order":list(CLASS_NAMES),"per_class":{name:{"precision":float(p[i]),"recall":float(r[i]),"support":int((np.asarray(true)==i).sum())} for i,name in enumerate(CLASS_NAMES)},
      "confusion_matrix":cm.tolist()}
    RESULTS_DIR.mkdir(parents=True,exist_ok=True)
    (RESULTS_DIR/"evaluation.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    fig,ax=plt.subplots(); ax.imshow(cm,cmap="Greens"); ax.set(xticks=range(3),yticks=range(3),xticklabels=CLASS_NAMES,yticklabels=CLASS_NAMES,xlabel="Predicted",ylabel="Actual")
    fig.tight_layout(); fig.savefig(RESULTS_DIR/"confusion_matrix.png",dpi=160); plt.close(fig); print(json.dumps(result,indent=2))
if __name__=="__main__": main()