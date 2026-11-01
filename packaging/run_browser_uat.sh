#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python -m pip install -r requirements-dev.txt
npm install
npx playwright install --with-deps chromium

python - <<'PY'
from reportlab.pdfgen import canvas

pdf = canvas.Canvas("/tmp/inquisitio_evidence.pdf")
pdf.drawString(72, 720, "Medical Record")
pdf.drawString(72, 690, "Jordan Moss sustained a cervical strain as a result of the incident.")
pdf.save()
PY

export INQUISITIO_DATA_DIR="$(mktemp -d)/cases"
python start_inquisitio.py --no-browser &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
for _ in {1..60}; do
    if curl --silent --fail http://127.0.0.1:8765/api/health >/dev/null; then
        break
    fi
    sleep 1
done
curl --silent --fail http://127.0.0.1:8765/api/health >/dev/null
npm run test:browser
