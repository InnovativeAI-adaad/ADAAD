# © InnovativeAI LLC — ADAAD Inside™ — All Rights Reserved
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.."; pwd)"
VER="$(cat "$ROOT/VERSION")"
OUT="$ROOT/releases/adaad-$VER.tar.gz"

echo "[build] assembling $OUT"
tar -czf "$OUT" \
  -C "$ROOT" \
  app data ui scripts tools \
  requirements-mobile.txt VERSION CHANGELOG.md

echo "[build] done -> $OUT"
