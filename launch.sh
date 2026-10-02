#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -x .venv/bin/python ]]; then
    exec .venv/bin/python run.py "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 run.py "$@"
else
    exec python run.py "$@"
fi
