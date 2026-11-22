import argparse,json
from .inference import load_predictor
def predict_image(image_path,device="auto"):
    predictor=load_predictor(device=device)
    with open(image_path,"rb") as f: return predictor.predict_bytes(f.read())
def main():
    p=argparse.ArgumentParser(); p.add_argument("--image",required=True); p.add_argument("--device",choices=("auto","cpu","cuda"),default="auto"); a=p.parse_args()
    print(json.dumps(predict_image(a.image,a.device),indent=2))
if __name__=="__main__": main()