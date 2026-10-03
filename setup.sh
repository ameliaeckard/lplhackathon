#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo
echo "R'Solv setup"
echo "==========="

python3 -m pip install -r requirements.txt

mkdir -p frontend/vendor

download() {
  local url="$1"
  local output="$2"

  if [ -s "$output" ]; then
    echo "Already present: $output"
    return 0
  fi

  echo "Downloading $output"

  if command -v curl >/dev/null 2>&1; then
    curl -L --fail "$url" -o "$output"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$output" "$url"
  else
    python3 - "$url" "$output" <<'PY'
import sys, urllib.request
url, output = sys.argv[1], sys.argv[2]
urllib.request.urlretrieve(url, output)
PY
  fi
}

download "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js" "frontend/vendor/pdf.min.js"
download "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js" "frontend/vendor/pdf.worker.min.js"
download "https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.2/jspdf.umd.min.js" "frontend/vendor/jspdf.umd.min.js"

if [ ! -f frontend/config.js ]; then
  cp frontend/config.example.js frontend/config.js
  echo
  echo "Created frontend/config.js from config.example.js."
  echo "If you use an AWS forwarded backend URL, edit frontend/config.js."
else
  echo "Preserved existing frontend/config.js"
fi

echo
if [ -f ml/models/resolve_model.joblib ]; then
  echo "Found trained model: ml/models/resolve_model.joblib"
else
  echo "WARNING: ml/models/resolve_model.joblib was not found."
  echo "Keep/copy your existing trained model into that location."
fi

if [ -f ml/model_features.py ]; then
  echo "Found existing feature code: ml/model_features.py"
else
  echo "WARNING: ml/model_features.py was not found."
  echo "Keep/copy your existing file; the backend imports it."
fi

echo
echo "Setup complete."
echo "Backend:  python3 backend/app.py"
echo "Frontend: python3 -m http.server 5500 --directory frontend"
