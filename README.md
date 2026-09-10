# Waste Classification — Model Training Task

## Goal
Train an image classifier that sorts a waste image into one of three categories:
`Hazardous`, `Organic`, `Recyclable`.

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

## Deploying to Vercel

The dataset itself isn't needed to deploy — only the already-trained model
(`model/waste_model.tflite`, ~9MB) is. A few things had to change from a
typical local Flask setup to make this work as a Vercel serverless function:

- **Model runtime**: the app runs `model/waste_model.tflite` via
  `ai-edge-litert` instead of full TensorFlow, since TensorFlow alone is
  too large for a serverless function bundle. If you retrain the model,
  regenerate the `.tflite` file with `python training/convert_to_tflite.py`
  (needs `training/requirements.txt`) — predictions are numerically
  identical to the `.h5` model, just running through a lighter interpreter.
- **Database**: already Postgres via `DATABASE_URL` (see `app/database.py`),
  so no change was needed there — just point it at a real Postgres instance.
  Easiest option: add a Postgres store (Neon integration) from your Vercel
  project's Storage tab, which sets `DATABASE_URL` for you automatically.
- **Uploaded photos**: Vercel's function filesystem is read-only except
  `/tmp`, and `/tmp` doesn't persist between requests. So uploaded images
  are saved to `/tmp` just long enough to run the classifier, then uploaded
  to **Vercel Blob** for permanent storage (shown later in history/admin
  dashboards). Add a Blob store from the Storage tab — it sets
  `BLOB_READ_WRITE_TOKEN` for you. Locally, or on any host with a normal
  persistent disk, this is skipped automatically and images just get saved
  to `app/static/uploads/` like before.

### Steps

1. Push this project to a Git repo (GitHub/GitLab/Bitbucket).
2. In Vercel: **Add New Project** → import the repo.
3. In the project's **Storage** tab, add:
   - A **Postgres** store (Neon integration) — sets `DATABASE_URL`.
   - A **Blob** store — sets `BLOB_READ_WRITE_TOKEN`.
4. In **Settings → Environment Variables**, add:
   - `SECRET_KEY` — a random value, e.g. `python -c "import secrets; print(secrets.token_hex(32))"`
   - `GROQ_API_KEY` — optional, free key from https://console.groq.com/keys
   - `FLASK_ENV=production`
5. Deploy. Vercel auto-detects `app/app.py` as the Flask entrypoint (no
   build command needed) — see `vercel.json` for the one setting that's
   configured (a 60s max duration, since the first classification after a
   cold start can take a few seconds).
6. On first request, `init_db()` creates the schema and a one-time admin
   login — check your deployment's function logs for the generated admin
   password (or set `ADMIN_USERNAME`/`ADMIN_PASSWORD` env vars beforehand,
   see `.env.example`).

`.vercelignore` excludes `training/`, `outputs/`, the old `.h5` model, and
the ~35MB of sample/test images in `app/static/uploads/` from the deployed
bundle, since none of that is needed at runtime.

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

