import torch
from torch import nn
from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights
from .config import CLASS_NAMES

def create_model(pretrained=False):
    weights=MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
    model=mobilenet_v3_small(weights=weights)
    model.classifier[-1]=nn.Linear(model.classifier[-1].in_features,len(CLASS_NAMES))
    return model

def freeze_features(model,freeze=True):
    for p in model.features.parameters(): p.requires_grad=not freeze
    for p in model.classifier.parameters(): p.requires_grad=True
