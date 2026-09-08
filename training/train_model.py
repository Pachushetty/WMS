"""
Waste Management System — CNN Training Script (Transfer Learning)
====================================================================

This script trains a waste classifier using TRANSFER LEARNING: a small
trainable head on top of MobileNetV2, a CNN pretrained on 1.4 million
general images (ImageNet). Instead of learning visual features (edges,
textures, shapes) from scratch on our ~3,200 images, we reuse
MobileNetV2's already-learned features and only train a small
classifier on top. This is standard practice for small/medium image
datasets and typically gives noticeably better accuracy than training a
CNN from scratch, especially on underrepresented classes.

Classifies waste images into exactly three categories:

    Hazardous, Organic, Recyclable

Workflow:
    Dataset
      -> Image preprocessing (resize + MobileNetV2 preprocessing)
      -> Data augmentation (training data only)
      -> MobileNetV2 (frozen, pretrained) + trainable classifier head
      -> Class-weighted training (to help the underrepresented
         Hazardous class) with EarlyStopping + ModelCheckpoint
      -> Model evaluation on validation data
      -> Accuracy / Loss graphs
      -> Classification report (precision, recall, f1-score)
      -> Confusion matrix
      -> Best trained model saved to disk

The dataset folder itself is never modified by this script — it is
only read from.

NOTE: the very first run downloads MobileNetV2's pretrained weights
(~14MB) from the internet. After that, they're cached locally and the
script works offline.
"""

from pathlib import Path

import numpy as np
import matplotlib
# Use a non-interactive backend so the script can run without a display
# (e.g. on a server or in a terminal) and still save graphs to disk.
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sklearn.metrics import classification_report, confusion_matrix, ConfusionMatrixDisplay
from sklearn.utils.class_weight import compute_class_weight

from tensorflow.keras import layers, models
from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras.applications.mobilenet_v2 import preprocess_input
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint


# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATASET_DIR = BASE_DIR / "dataset"
MODEL_DIR = BASE_DIR / "model"
MODEL_PATH = MODEL_DIR / "waste_model.h5"
OUTPUTS_DIR = BASE_DIR / "outputs"

# The three classes this project must always classify into.
# Keeping this explicit list lets us clearly check the dataset folders
# match what we expect, and lets us map predictions back to readable names.
EXPECTED_CLASSES = ["Hazardous", "Organic", "Recyclable"]

IMAGE_SIZE = (224, 224)
BATCH_SIZE = 32
EPOCHS = 30  # EarlyStopping will usually stop training well before this


# ---------------------------------------------------------------------------
# Step 1: Validate the dataset folder before doing anything else
# ---------------------------------------------------------------------------
def validate_dataset():
    """
    Check that the dataset folder and all three expected class folders
    exist and contain at least one image. Raises a clear, descriptive
    error instead of letting Keras fail with a confusing message later.
    """
    if not DATASET_DIR.exists():
        raise FileNotFoundError(
            f"Dataset folder not found: {DATASET_DIR}\n"
            "Expected a 'dataset' folder containing one sub-folder per "
            "class (Hazardous, Organic, Recyclable)."
        )

    valid_extensions = {".jpg", ".jpeg", ".png", ".bmp"}

    for class_name in EXPECTED_CLASSES:
        class_dir = DATASET_DIR / class_name
        if not class_dir.exists():
            raise FileNotFoundError(
                f"Missing expected class folder: {class_dir}\n"
                f"The dataset must contain these folders: {EXPECTED_CLASSES}"
            )

        image_files = [
            f for f in class_dir.iterdir()
            if f.is_file() and f.suffix.lower() in valid_extensions
        ]
        if len(image_files) == 0:
            raise FileNotFoundError(
                f"No readable images (.jpg/.jpeg/.png/.bmp) found in: {class_dir}\n"
                "Note: formats like .gif and .svg are not supported by the "
                "image loader used here and will be skipped."
            )

    print("Dataset check passed. Found folders for:", EXPECTED_CLASSES)


# ---------------------------------------------------------------------------
# Step 2: Preprocessing + data augmentation
# ---------------------------------------------------------------------------
def build_data_generators():
    """
    Create separate generators for training and validation data.

    - Training data: preprocessed for MobileNetV2 AND augmented, so the
      model sees varied versions of each image and generalizes better.
    - Validation data: preprocessed for MobileNetV2 ONLY. No random
      augmentation is applied, so validation results reflect real,
      unaltered images.

    NOTE: we use MobileNetV2's own preprocess_input() instead of a plain
    1/255 rescale. MobileNetV2 was trained with a specific input scaling
    (roughly -1 to 1, not 0 to 1), so using the wrong scaling here would
    silently hurt accuracy even though the code would still run without
    errors. The Flask app's prediction code must use this exact same
    preprocessing for predictions to be correct.
    """
    train_datagen = ImageDataGenerator(
        preprocessing_function=preprocess_input,  # MobileNetV2-specific normalization
        validation_split=0.2,       # 80% train / 20% validation split
        rotation_range=20,          # randomly rotate images up to 20 degrees
        width_shift_range=0.2,      # randomly shift images horizontally
        height_shift_range=0.2,     # randomly shift images vertically
        zoom_range=0.2,             # randomly zoom in/out
        horizontal_flip=True,       # randomly flip images left-right
        fill_mode="nearest",        # how to fill in pixels created by shifts
    )

    # Validation data uses the SAME split so it comes from the same
    # source folders, but only preprocessing is applied — no augmentation.
    val_datagen = ImageDataGenerator(
        preprocessing_function=preprocess_input,
        validation_split=0.2,
    )

    train_data = train_datagen.flow_from_directory(
        DATASET_DIR,
        target_size=IMAGE_SIZE,
        batch_size=BATCH_SIZE,
        class_mode="categorical",
        classes=EXPECTED_CLASSES,   # force a fixed, known class order
        subset="training",
        shuffle=True,
        seed=42,
    )

    val_data = val_datagen.flow_from_directory(
        DATASET_DIR,
        target_size=IMAGE_SIZE,
        batch_size=BATCH_SIZE,
        class_mode="categorical",
        classes=EXPECTED_CLASSES,   # same fixed order as training
        subset="validation",
        shuffle=False,               # keep order stable for evaluation
        seed=42,
    )

    return train_data, val_data


# ---------------------------------------------------------------------------
# Step 3: Transfer learning model (MobileNetV2 + custom classifier head)
# ---------------------------------------------------------------------------
def build_model(num_classes: int):
    """
    Transfer learning architecture:
      - MobileNetV2 (pretrained on ImageNet) as a FROZEN feature
        extractor — its convolutional layers already know how to
        recognize general visual features (edges, textures, shapes,
        materials) from 1.4 million images, so we reuse that knowledge
        instead of learning it from scratch on our much smaller dataset.
      - GlobalAveragePooling2D condenses MobileNetV2's output into a
        compact feature vector.
      - A small trainable head (Dense + Dropout + output) learns to map
        those general features onto our 3 specific waste categories.
      - ReLU activation in the hidden layer, Softmax on the output layer
        (turns outputs into class probabilities that sum to 1).
    """
    base_model = MobileNetV2(
        input_shape=(224, 224, 3),
        include_top=False,   # exclude MobileNetV2's original 1000-class ImageNet head
        weights="imagenet",  # pretrained weights (downloaded once, cached after)
    )
    base_model.trainable = False  # freeze: keep pretrained features intact

    model = models.Sequential([
        base_model,
        layers.GlobalAveragePooling2D(),
        layers.Dense(128, activation="relu"),
        layers.Dropout(0.5),
        layers.Dense(num_classes, activation="softmax"),
    ])

    model.compile(
        optimizer="adam",
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model


# ---------------------------------------------------------------------------
# Step 3b: Class weights (to help the underrepresented Hazardous class)
# ---------------------------------------------------------------------------
def compute_weights(train_data):
    """
    Our dataset is imbalanced (fewer Hazardous images than Organic or
    Recyclable). Without correction, the model can learn to favor the
    larger classes since getting them right matters more to the average
    loss. Class weights counteract this by penalizing mistakes on
    underrepresented classes more heavily during training.
    """
    labels = train_data.classes  # integer label for every training image
    unique_classes = np.unique(labels)

    weights = compute_class_weight(
        class_weight="balanced",
        classes=unique_classes,
        y=labels,
    )
    class_weight_dict = dict(zip(unique_classes.tolist(), weights.tolist()))

    print("Class weights (higher = more emphasis during training):")
    for class_index, weight in class_weight_dict.items():
        print(f"  {class_index}: {weight:.3f}")

    return class_weight_dict


# ---------------------------------------------------------------------------
# Step 4: Training callbacks
# ---------------------------------------------------------------------------
def build_callbacks():
    """
    EarlyStopping: stops training once validation loss stops improving,
        and restores the best weights seen during training.
    ModelCheckpoint: saves a copy of the model every time validation
        loss improves, so the BEST model (not just the last epoch)
        ends up saved to disk.

    IMPORTANT: both callbacks monitor the SAME metric (val_loss). If they
    monitored different metrics (e.g. one on val_accuracy, one on
    val_loss), they could each consider a different epoch "best", and the
    final model.save() after training — which saves whatever weights
    EarlyStopping restored — could silently overwrite a better checkpoint
    that ModelCheckpoint had already saved under a different metric.
    """
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    early_stopping = EarlyStopping(
        monitor="val_loss",
        patience=5,
        restore_best_weights=True,
        verbose=1,
    )

    checkpoint = ModelCheckpoint(
        filepath=str(MODEL_PATH),
        monitor="val_loss",
        save_best_only=True,
        verbose=1,
    )

    return [early_stopping, checkpoint]


# ---------------------------------------------------------------------------
# Step 5: Plot accuracy/loss graphs
# ---------------------------------------------------------------------------
def plot_training_history(history):
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    # --- Accuracy plot ---
    plt.figure()
    plt.plot(history.history["accuracy"], label="Train Accuracy")
    plt.plot(history.history["val_accuracy"], label="Validation Accuracy")
    plt.title("Training vs Validation Accuracy")
    plt.xlabel("Epoch")
    plt.ylabel("Accuracy")
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTPUTS_DIR / "accuracy_plot.png")
    plt.close()

    # --- Loss plot ---
    plt.figure()
    plt.plot(history.history["loss"], label="Train Loss")
    plt.plot(history.history["val_loss"], label="Validation Loss")
    plt.title("Training vs Validation Loss")
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.legend()
    plt.tight_layout()
    plt.savefig(OUTPUTS_DIR / "loss_plot.png")
    plt.close()

    print(f"Accuracy/Loss graphs saved to: {OUTPUTS_DIR}")


# ---------------------------------------------------------------------------
# Step 6: Evaluation, classification report, confusion matrix
# ---------------------------------------------------------------------------
def evaluate_model(model, val_data, class_names):
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    # Overall loss/accuracy on the validation set
    val_loss, val_accuracy = model.evaluate(val_data, verbose=0)
    print(f"Validation Loss: {val_loss:.4f}")
    print(f"Validation Accuracy: {val_accuracy:.4f}")

    # Get true labels and predicted labels for every validation image
    val_data.reset()
    predictions = model.predict(val_data, verbose=0)
    predicted_classes = np.argmax(predictions, axis=1)
    true_classes = val_data.classes  # true labels, in the same fixed order

    # Classification report: precision, recall, f1-score per class
    report = classification_report(
        true_classes,
        predicted_classes,
        target_names=class_names,
        zero_division=0,
    )
    print("\nClassification Report:\n")
    print(report)

    report_path = OUTPUTS_DIR / "classification_report.txt"
    with open(report_path, "w") as f:
        f.write(f"Validation Loss: {val_loss:.4f}\n")
        f.write(f"Validation Accuracy: {val_accuracy:.4f}\n\n")
        f.write(report)
    print(f"Classification report saved to: {report_path}")

    # Confusion matrix
    cm = confusion_matrix(true_classes, predicted_classes)
    disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=class_names)
    fig, ax = plt.subplots(figsize=(6, 6))
    disp.plot(ax=ax, cmap="Blues", colorbar=False)
    plt.title("Confusion Matrix")
    plt.tight_layout()
    cm_path = OUTPUTS_DIR / "confusion_matrix.png"
    plt.savefig(cm_path)
    plt.close()
    print(f"Confusion matrix saved to: {cm_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # 1. Make sure the dataset is present and looks correct before training
    validate_dataset()

    # 2. Preprocessing + augmentation
    train_data, val_data = build_data_generators()

    # Class names in the fixed order defined by EXPECTED_CLASSES.
    # train_data.class_indices maps e.g. {'Hazardous': 0, 'Organic': 1, 'Recyclable': 2}
    class_indices = train_data.class_indices
    class_names = sorted(class_indices, key=class_indices.get)
    print("Class mapping:", class_indices)

    # 3. Build the transfer learning model
    model = build_model(num_classes=len(class_names))
    model.summary()

    # 4. Compute class weights to help the underrepresented Hazardous class
    class_weights = compute_weights(train_data)

    # 5. Train with EarlyStopping + ModelCheckpoint + class weighting
    callbacks = build_callbacks()
    history = model.fit(
        train_data,
        validation_data=val_data,
        epochs=EPOCHS,
        callbacks=callbacks,
        class_weight=class_weights,
    )

    # Make sure the best model is saved even if ModelCheckpoint didn't
    # trigger on the very last epoch (e.g. training stopped early).
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model.save(MODEL_PATH)
    print(f"\nBest model saved to: {MODEL_PATH}")

    # 6. Accuracy / Loss graphs
    plot_training_history(history)

    # 7. Evaluation + classification report + confusion matrix
    evaluate_model(model, val_data, class_names)


if __name__ == "__main__":
    main()
