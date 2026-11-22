import json, random, time
from pathlib import Path
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader
from sklearn.metrics import f1_score
from .config import *
from .dataset import ManifestDataset
from .model import create_model, freeze_features

def seed_all(seed=SEED):
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic=True
        torch.backends.cudnn.benchmark=False
def epoch(model,loader,device,opt=None):
    training=opt is not None; model.train(training); loss_fn=nn.CrossEntropyLoss(); loss_sum=0; ys=[]; ps=[]
    for x,y in loader:
        x=x.to(device); y=y.to(device)
        if training: opt.zero_grad(set_to_none=True)
        with torch.set_grad_enabled(training):
            out=model(x); loss=loss_fn(out,y)
            if training: loss.backward(); opt.step()
        loss_sum+=loss.item()*y.size(0); ps.extend(out.argmax(1).cpu().tolist()); ys.extend(y.cpu().tolist())
    return {'loss':loss_sum/max(1,len(ys)),'accuracy':sum(a==b for a,b in zip(ys,ps))/max(1,len(ys)),'macro_f1':f1_score(ys,ps,average='macro',zero_division=0)},ys,ps

def main():
    seed_all(); device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    train=DataLoader(ManifestDataset(MANIFEST_DIR/'train.csv',True),batch_size=BATCH_SIZE,shuffle=True,num_workers=0)
    val=DataLoader(ManifestDataset(MANIFEST_DIR/'validation.csv'),batch_size=BATCH_SIZE,num_workers=0)
    model=create_model(pretrained=True).to(device); history=[]; best=-1
    stages=[('head',5,True,1e-3),('finetune',5,False,1e-4)]
    MODELS_DIR.mkdir(parents=True,exist_ok=True)
    RESULTS_DIR.mkdir(parents=True,exist_ok=True)
    for stage,epochs,freeze,lr in stages:
        freeze_features(model,freeze); opt=torch.optim.AdamW((p for p in model.parameters() if p.requires_grad),lr=lr)
        scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(opt,T_max=epochs)
        for e in range(epochs):
            tr,_,_=epoch(model,train,device,opt); va,_,_=epoch(model,val,device); scheduler.step()
            rec={'stage':stage,'epoch':e+1,'train':tr,'validation':va}; history.append(rec); print(json.dumps(rec))
            if va['macro_f1']>best:
                best=va['macro_f1']; torch.save({'state_dict':model.state_dict(),'architecture':'mobilenet_v3_small','class_names':list(CLASS_NAMES),'input_size':INPUT_SIZE,'normalization':'imagenet','validation_macro_f1':best,'version':1},CHECKPOINT_PATH)
        with (RESULTS_DIR/'training_history.json').open('w') as f: json.dump(history,f,indent=2)
if __name__=='__main__': main()
