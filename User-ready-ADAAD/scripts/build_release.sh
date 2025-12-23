#!/data/data/com.termux/files/usr/bin/env sh

set -eu

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "${PROJECT_ROOT}/.." && pwd)"
VERSION_FILE="${REPO_ROOT}/VERSION"
CHANGELOG_FILE="${REPO_ROOT}/CHANGELOG.md"

if [ ! -f "$VERSION_FILE" ]; then
  echo "VERSION file missing"
  exit 1
fi

VERSION="$(cat "$VERSION_FILE")"
OUTPUT_DIR="${PROJECT_ROOT}/releases"
ARCHIVE_NAME="adaad-${VERSION}.tar.gz"
ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_NAME}"

mkdir -p "$OUTPUT_DIR"

tar --exclude="User-ready-ADAAD/archives" --exclude="User-ready-ADAAD/experiments/*" \
  -czf "$ARCHIVE_PATH" \
  -C "$REPO_ROOT" \
  User-ready-ADAAD VERSION CHANGELOG.md User-ready-ADAAD/MANIFEST.txt

echo "Release created at ${ARCHIVE_PATH}"
