#!/bin/bash
# SessionStart hook — install Python dependencies so tests/linters work
# in Claude Code on the web sessions.
set -euo pipefail

# Only run in the remote (web) environment; locally the user manages their own venv.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

echo "[session-start] Installing Python dependencies from requirements.txt..."
python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt

echo "[session-start] Done."
