#!/usr/bin/env bash
# ./run.sh app       start the web app (port 8501, reachable over Tailscale)
# ./run.sh test      check both model servers
# ./run.sh ingest    add the sample documents in data/docs to the records
# ./run.sh bench     run the benchmark, writes benchmarks/RESULTS.md
# ./run.sh reset     rebuild the databases from scratch (keeps data files)
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
[ -f .env ] && { set -a; source .env; set +a; }

case "${1:-app}" in
  app)    exec streamlit run app.py --server.address 0.0.0.0 --server.port "${CAREEDGE_PORT:-8501}" ;;
  test)   python test_models.py ;;
  ingest) python ingest.py ;;
  bench)  python benchmark.py ;;
  reset)  rm -f data/patient.db data/rag.db data/events.db; rm -rf uploads
          python -c "import patient_db; patient_db.build(); print('Rebuilt data/patient.db')" ;;
  *)      echo "usage: ./run.sh [app|test|ingest|bench|reset]"; exit 1 ;;
esac
