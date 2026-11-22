import io,sys,types,unittest
from PIL import Image
try:
    import fastapi
    from fastapi.testclient import TestClient
    from ml.config import CLASS_NAMES
    fake=types.ModuleType("ml.inference")
    class StubPredictor:
        device="cpu"
        metadata={"version":1}
        def predict_bytes(self,data):
            return {"crop":"tomato","predicted_class":"healthy","top_predicted_class":"healthy","top_prediction_score":.8,
                    "class_scores":{"healthy":.8,"early_blight":.1,"late_blight":.1},
                    "prediction_status":"prediction_available","score_note":"Not calibrated probabilities."}
    fake.load_predictor=lambda:StubPredictor()
    sys.modules["ml.inference"]=fake
    from api.main import app
    AVAILABLE=True
except ImportError:
    AVAILABLE=False
@unittest.skipUnless(AVAILABLE,"FastAPI/httpx test dependencies are not installed")
class ApiTests(unittest.TestCase):
    def setUp(self): self.client=TestClient(app); self.client.__enter__()
    def tearDown(self): self.client.__exit__(None,None,None)
    def png(self):
        image=Image.new("RGB",(8,8),(30,150,50)); out=io.BytesIO(); image.save(out,format="PNG"); return out.getvalue()
    def test_health_and_model_info(self):
        self.assertTrue(self.client.get("/health").json()["model_loaded"])
        info=self.client.get("/api/model-info").json()
        self.assertEqual(info["supported_classes"],list(CLASS_NAMES)); self.assertEqual(info["device"],"cpu")
    def test_valid_image_prediction(self):
        r=self.client.post("/api/predict",files={"image":("leaf.png",self.png(),"image/png")})
        self.assertEqual(r.status_code,200); body=r.json()
        self.assertEqual(body["predicted_class"],"healthy")
        self.assertEqual(set(body["class_scores"]),set(CLASS_NAMES))
    def test_invalid_image_and_type(self):
        bad=self.client.post("/api/predict",files={"image":("leaf.png",b"not an image","image/png")})
        self.assertEqual(bad.status_code,400)
        wrong=self.client.post("/api/predict",files={"image":("leaf.txt",b"abc","text/plain")})
        self.assertEqual(wrong.status_code,415)
    def test_missing_image_is_rejected(self): self.assertEqual(self.client.post("/api/predict").status_code,422)
    def test_oversized_upload_is_rejected(self):
        r=self.client.post("/api/predict",files={"image":("large.png",b"x"*(10*1024*1024+1),"image/png")})
        self.assertEqual(r.status_code,413)
    def test_missing_model_is_reported(self):
        previous=app.state.predictor
        try:
            app.state.predictor=None
            r=self.client.post("/api/predict",files={"image":("leaf.png",self.png(),"image/png")})
            self.assertEqual(r.status_code,503)
        finally: app.state.predictor=previous
if __name__=="__main__": unittest.main()