#!/usr/bin/env bash
# One-time setup on the ZGX Nano. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv || { echo "python3-venv is missing: sudo apt install -y python3-venv"; exit 1; }
fi
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

[ -f .env ] || cp .env.example .env
chmod +x run.sh serve_models.sh

python make_dataset.py
python -c "import patient_db; patient_db.build(); print('Built data/patient.db')"

echo
echo "Setup done. Next:"
echo "  1. ./serve_models.sh embed     (terminal 1)"
echo "  2. ./serve_models.sh llm       (terminal 2)"
echo "  3. ./run.sh test"
echo "  4. ./run.sh ingest"
echo "  5. ./run.sh app"
