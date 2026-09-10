# Waste Classification — Model Training Task

## Goal
Train an image classifier that sorts a waste image into one of three categories:
`Hazardous`, `Organic`, `Recyclable`.
## Dataset

The waste classification dataset used for training the EcoCycle
waste detection model is available on Kaggle.

**Dataset:** [Waste Items Dataset](https://www.kaggle.com/datasets/pachu08/waste-items)

The dataset was used to train the waste classification model.
The trained model is available in:

`model/waste_model.h5`

## What you have
```
.
├── dataset/
│   ├── Hazardous/     (676 images)
│   ├── Organic/       (1401 images)
│   └── Recyclable/    (1112 images)
├── training/
│   └── train_model.py
└── requirements.txt
```

## Setup
```
pip install -r requirements.txt
```

## Running the web app (app/app.py)
The web app additionally uses the Groq API (a vision-language model) to:
1. Check whether the uploaded photo actually looks like a waste item at
   all (gatekeeping out things like people, pets, or diagrams).
2. Name the specific item (e.g. "plastic water bottle", "AA battery").

Both are separate from, and don't affect, the Hazardous/Organic/Recyclable
CNN classifier above.

1. Copy `.env.example` to `.env` in this folder.
2. Get a free API key at https://console.groq.com/keys and put it in `.env`
   as `GROQ_API_KEY=...`.
3. Run `python app/app.py`.

If `GROQ_API_KEY` isn't set, the app still runs — it just skips the
waste pre-check and item naming and goes straight to the CNN classifier.

## Train
From inside the `training/` folder, run:
```
python train_model.py
```
This will:
- Validate that `../dataset/` and its three class folders exist and
  contain readable images (clear error messages if not).
- Load images from `../dataset/`, preprocess them for MobileNetV2, and
  apply data augmentation (rotation, width/height shift, zoom,
  horizontal flip) to the training set only. Validation images are only
  preprocessed, never augmented.
- Train using **transfer learning**: a frozen, pretrained MobileNetV2
  (ImageNet weights) as the feature extractor, with a small trainable
  classifier head (Dense + Dropout + output) on top. This reuses
  MobileNetV2's general visual knowledge instead of learning everything
  from scratch, and typically performs noticeably better than a
  from-scratch CNN on a dataset this size.
- Apply **class weighting** during training, since the dataset is
  imbalanced (fewer Hazardous images than Organic or Recyclable) — this
  penalizes mistakes on the underrepresented class more heavily.
- Train for up to 30 epochs, with EarlyStopping and ModelCheckpoint
  (both watching validation loss, so they always agree on which epoch
  is "best" — keeps only the best-performing model).
- Save the best trained model to `../model/waste_model.h5`.
- Print the class-index mapping it learned (should be
  `{'Hazardous': 0, 'Organic': 1, 'Recyclable': 2}`).
- Evaluate the model on the validation data and save, to `../outputs/`:
  - `accuracy_plot.png` and `loss_plot.png` — training vs validation curves
  - `classification_report.txt` — precision, recall, f1-score per class
  - `confusion_matrix.png` — confusion matrix image

## Notes
- Images are resized to 224x224 and preprocessed using MobileNetV2's
  `preprocess_input` (scales pixels to roughly -1 to 1, NOT a plain 0-1
  rescale). The Flask app (`app/app.py`) uses this exact same
  preprocessing when predicting — if you ever change one, you must
  change the other, or predictions will be silently wrong.
- The very first training run downloads MobileNetV2's pretrained
  weights (~14MB) from the internet; after that they're cached locally
  and training works offline.
- 20% of the data is held out automatically for validation.
- A few `.gif` and `.svg` files in the dataset are not readable by the
  image loader and will be silently skipped — this is expected and not
  a bug.
- Possible future improvements:
  - Unfreezing some of MobileNetV2's later layers for fine-tuning
    (with a low learning rate) once the classifier head is trained
  - Adding more Hazardous training images, especially for
    underrepresented items like batteries
  - Checking whether performance differs a lot across the three
    classes and investigating why

