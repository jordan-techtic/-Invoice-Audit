#!/usr/bin/env bash
# Optional: local object storage for invoice uploads (matches api defaults).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/.local/bin/minio"
DATA="$ROOT/.local/minio-data"
mkdir -p "$DATA" "$ROOT/.local/bin"

if [[ ! -x "$BIN" ]]; then
  echo "Downloading MinIO to $BIN (one-time)…"
  tag="RELEASE.2024-12-18T13-15-44Z"
  curl -fsSL -o "$BIN" \
    "https://github.com/minio/minio/releases/download/${tag}/minio.linux-amd64.${tag}"
  chmod +x "$BIN"
fi

export MINIO_ROOT_USER=minioadmin
export MINIO_ROOT_PASSWORD=minioadmin
echo "MinIO API: http://127.0.0.1:9000  Console: http://127.0.0.1:9001"
exec "$BIN" server "$DATA" --address ":9000" --console-address ":9001"