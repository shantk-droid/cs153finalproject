#!/usr/bin/env bash
# Generate three demo CSVs in data/samples/.
# Run from repo root after `pip install -e apps/api`.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p data/samples

echo "Generating retail_stable.csv"
PYTHONPATH="$REPO_ROOT" python3 -m apps.api.synthetic --template retail_stable --out data/samples/retail_stable.csv

echo "Generating coffee_perishable.csv"
PYTHONPATH="$REPO_ROOT" python3 -m apps.api.synthetic --template coffee_perishable --out data/samples/coffee_perishable.csv

echo "Generating ecommerce_lumpy.csv"
PYTHONPATH="$REPO_ROOT" python3 -m apps.api.synthetic --template ecommerce_lumpy --out data/samples/ecommerce_lumpy.csv

echo
ls -lh data/samples/
