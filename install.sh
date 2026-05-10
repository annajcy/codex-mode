#!/usr/bin/env bash
set -euo pipefail

echo "=== codex-mode installer ==="

# 1. Install Python CLI
echo "› Installing codex-mode..."
uv tool install -e .

# 2. Build & link codeproxy from submodule
SUBMODULE_DIR="$(dirname "$0")/vendor/codeproxy"
if [ -d "$SUBMODULE_DIR" ]; then
    echo "› Installing codeproxy from submodule..."
    cd "$SUBMODULE_DIR"
    npm install --ignore-scripts
    npm run build
    npm link
    cd - > /dev/null
else
    echo "! vendor/codeproxy not found — run: git submodule update --init"
fi

echo "=== Done ==="
echo "Run 'codex-mode --help' and 'codeproxy --help' to verify."
