#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m venv env || true
. env/bin/activate
pip install --upgrade pip
pip install -r requirements-mobile.txt
echo "OK"
