#!/usr/bin/env bash
set -e

PORT="${PORT:-3000}"
HOST="${HOST:-0.0.0.0}"
NODE_ENV="${NODE_ENV:-production}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if [[ ! -d "node_modules" || ! -d ".next" ]]; then
  echo "Fire PM Web UI is not built yet. Building now..."
  if command -v pnpm &>/dev/null; then
    pnpm install --prod=false
    pnpm build
  elif command -v npm &>/dev/null; then
    npm install
    npm run build
  else
    echo "Error: Node.js (v22+) and pnpm/npm are required to run the Web UI."
    exit 1
  fi
fi

echo "Starting Fire PM Web UI on http://${HOST}:${PORT}..."
exec ./node_modules/.bin/next start -p "${PORT}" -H "${HOST}"
