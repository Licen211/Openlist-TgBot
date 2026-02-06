#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="Openlist-TgBot"
OUTPUT_DIR="dist"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE_NAME="${PROJECT_NAME}-${TIMESTAMP}.tar.gz"

mkdir -p "$OUTPUT_DIR"

tar \
  --exclude='./.git' \
  --exclude='./.venv' \
  --exclude='./__pycache__' \
  --exclude='./dist' \
  -czf "${OUTPUT_DIR}/${ARCHIVE_NAME}" .

echo "打包完成: ${OUTPUT_DIR}/${ARCHIVE_NAME}"
