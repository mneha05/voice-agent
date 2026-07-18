#!/usr/bin/env bash
# One-shot dev launcher (macOS / Linux)
set -euo pipefail
cd "$(dirname "$0")/.."

[ -d .venv ] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env — add your DEEPGRAM_API_KEY and LLM key, then re-run."
  exit 1
fi

python -m server.main
