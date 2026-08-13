#!/usr/bin/env bash
set -e

PORT="${PORT:-3000}"
HOST="${HOST:-0.0.0.0}"
NODE_ENV="${NODE_ENV:-production}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "Starting Fire PM Web UI on http://${HOST}:${PORT}..."
exec ./node_modules/.bin/next start -p "${PORT}" -H "${HOST}"
