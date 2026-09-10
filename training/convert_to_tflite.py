"""
Converts model/waste_model.h5 (produced by train_model.py) into
model/waste_model.tflite, which is what the deployed Flask app actually
loads (see app/app.py). Run this once after every retrain.

Requires TensorFlow (training/requirements.txt) — NOT needed by the deployed
app itself, which uses the much smaller ai-edge-litert runtime instead.

Usage (from the training/ folder):
    python convert_to_tflite.py
"""

from pathlib import Path

import tensorflow as tf

BASE_DIR = Path(__file__).resolve().parent.parent
H5_PATH = BASE_DIR / "model" / "waste_model.h5"
TFLITE_PATH = BASE_DIR / "model" / "waste_model.tflite"


def main() -> None:
    if not H5_PATH.exists():
        raise FileNotFoundError(
            f"{H5_PATH} not found — run train_model.py first."
        )

    print(f"Loading {H5_PATH} ...")
    model = tf.keras.models.load_model(H5_PATH)

    print("Converting to TensorFlow Lite ...")
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    tflite_model = converter.convert()

    TFLITE_PATH.write_bytes(tflite_model)
    print(f"Wrote {TFLITE_PATH} ({TFLITE_PATH.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
