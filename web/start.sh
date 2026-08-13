#!/usr/bin/env bash
set -e

PORT="${PORT:-3000}"
HOST="${HOST:-0.0.0.0}"
NODE_ENV="${NODE_ENV:-production}"

cd /root/fire-pm

echo "Starting Fire PM Web UI on http://${HOST}:${PORT}..."
exec ./node_modules/.bin/next start -p "${PORT}" -H "${HOST}"
