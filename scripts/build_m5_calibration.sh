#!/usr/bin/env bash
# Download M5 raw files (via Kaggle CLI) and build the calibration artifacts.
#
# Prerequisites:
#   1. `pip install kaggle` (and put your Kaggle API token at ~/.kaggle/kaggle.json)
#   2. Accept the M5 competition rules on Kaggle once: https://www.kaggle.com/competitions/m5-forecasting-accuracy/rules
#   3. Activate the api venv and `pip install -e apps/api`
#
# Run from repo root:
#   bash scripts/build_m5_calibration.sh
#
# Optional: faster dev build with a sampled subset of SKUs:
#   bash scripts/build_m5_calibration.sh --sample-skus 2000

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAW_DIR="$REPO_ROOT/apps/api/m5/raw"
OUT_DIR="$REPO_ROOT/apps/api/m5/artifacts"

mkdir -p "$RAW_DIR" "$OUT_DIR"

if [[ ! -f "$RAW_DIR/sales_train_evaluation.csv" ]]; then
  if ! command -v kaggle &> /dev/null; then
    echo "Error: kaggle CLI not found."
    echo "Install with: pip install kaggle"
    echo "Then save your token at: ~/.kaggle/kaggle.json (chmod 600)"
    exit 1
  fi

  echo "Downloading M5 from Kaggle into $RAW_DIR"
  kaggle competitions download -c m5-forecasting-accuracy -p "$RAW_DIR"
  unzip -o "$RAW_DIR/m5-forecasting-accuracy.zip" -d "$RAW_DIR"
  rm -f "$RAW_DIR/m5-forecasting-accuracy.zip"
else
  echo "M5 raw files already present in $RAW_DIR — skipping download"
fi

echo "Building calibration artifacts -> $OUT_DIR"
cd "$REPO_ROOT"
python -m apps.api.m5.build_calibration --raw "$RAW_DIR" --out "$OUT_DIR" "$@"

echo
echo "Done. Artifacts:"
ls -lh "$OUT_DIR"
