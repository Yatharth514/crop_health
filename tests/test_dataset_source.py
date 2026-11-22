from pathlib import Path
from PIL import Image
import tempfile, unittest
from ml.dataset_source import parse_color_record
from ml.prepare_dataset import sha256_file, exclude_train_test_duplicates, missing_target_classes, validate_rgb
class DatasetSourceTests(unittest.TestCase):
    def test_path_schema_and_color_tomato_mapping(self):
        row=parse_color_record({"text":"raw/color/Tomato___Early_blight/img.jpg"},"train")
        self.assertEqual(row["label"],"early_blight")
        self.assertEqual(row["source_label"],"Tomato___Early_blight")
        self.assertIsNone(parse_color_record({"text":"raw/grayscale/Tomato___healthy/img.jpg"},"train"))
        self.assertIsNone(parse_color_record({"text":"raw/color/Potato___healthy/img.jpg"},"train"))
    def test_three_target_classes_are_checked(self):
        self.assertEqual(missing_target_classes([{"label":"healthy"},{"label":"early_blight"},{"label":"late_blight"}]),[])
        self.assertEqual(missing_target_classes([{"label":"healthy"}]),["early_blight","late_blight"])
    def test_valid_image_is_decoded_as_rgb(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"gray.png"; Image.new("L",(7,5),128).save(path)
            self.assertEqual(validate_rgb(path),(7,5))
    def test_unexpected_schema_is_rejected(self):
        with self.assertRaises(ValueError): parse_color_record({"image":"x.jpg"},"train")
    def test_hash_is_content_based(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/"one"; b=Path(d)/"two"; a.write_bytes(b"same bytes"); b.write_bytes(b"same bytes")
            self.assertEqual(sha256_file(a),sha256_file(b))
    def test_duplicate_test_copy_removed_from_training(self):
        train=[{"image_path":"train/a","sha256":"dup"},{"image_path":"train/b","sha256":"unique"}]
        test=[{"image_path":"test/a","sha256":"dup"}]
        kept,excluded=exclude_train_test_duplicates(train,test)
        self.assertEqual([r["image_path"] for r in kept],["train/b"])
        self.assertEqual([r["image_path"] for r in excluded],["train/a"])
        self.assertEqual(test[0]["image_path"],"test/a")
if __name__=="__main__": unittest.main()