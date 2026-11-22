import io
from pathlib import Path
import torch
from PIL import Image, UnidentifiedImageError
from torchvision import transforms
from .config import CLASS_NAMES, CHECKPOINT_PATH, INPUT_SIZE
from .model import create_model

def choose_device(preference='auto'):
    if preference=='cpu': return torch.device('cpu')
    if preference=='cuda' and torch.cuda.is_available(): return torch.device('cuda')
    if preference=='cuda': raise RuntimeError('CUDA was requested but is not available')
    return torch.device('cuda' if torch.cuda.is_available() else 'cpu')
def load_predictor(checkpoint=CHECKPOINT_PATH,device='auto'):
    dev=choose_device(device); checkpoint=Path(checkpoint)
    if not checkpoint.is_file(): raise FileNotFoundError('Trained checkpoint is missing')
    payload=torch.load(checkpoint,map_location=dev,weights_only=True)
    if payload.get('architecture')!='mobilenet_v3_small' or tuple(payload.get('class_names',()))!=CLASS_NAMES:
        raise ValueError('Checkpoint architecture or class order is incompatible')
    model=create_model(False); model.load_state_dict(payload['state_dict']); model.to(dev).eval()
    tx=transforms.Compose([transforms.Resize((INPUT_SIZE,INPUT_SIZE)),transforms.ToTensor(),transforms.Normalize((.485,.456,.406),(.229,.224,.225))])
    return Predictor(model,dev,tx,payload)
class Predictor:
    def __init__(self,model,device,transform,metadata): self.model=model; self.device=device; self.transform=transform; self.metadata=metadata
    def predict_bytes(self,content):
        try:
            with Image.open(io.BytesIO(content)) as im: x=self.transform(im.convert('RGB')).unsqueeze(0).to(self.device)
        except (OSError,UnidentifiedImageError,ValueError) as e: raise ValueError('Image contents could not be decoded') from e
        with torch.inference_mode(): scores=self.model(x).softmax(1)[0].cpu().tolist()
        result=dict(zip(CLASS_NAMES,(float(v) for v in scores)))
        label=max(result,key=result.get)
        return {'crop':'tomato','predicted_class':label,'top_predicted_class':label,'top_prediction_score':result[label],
          'class_scores':result,'prediction_status':'prediction_available','score_note':'Model scores are softmax outputs, not calibrated probabilities.'}
