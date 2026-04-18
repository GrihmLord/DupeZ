#!/usr/bin/env bash
# Regenerate requirements-locked.txt from requirements.in with wheel hashes.
#
# Pins every direct and transitive dependency to a single wheel hash so
# `pip install --require-hashes` can verify supply-chain integrity.
#
# Usage:
#     scripts/lock-requirements.sh           # regenerate
#     scripts/lock-requirements.sh --upgrade # bump to latest allowed

set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
UPGRADE_FLAG=""
for arg in "$@"; do
    case "$arg" in
        --upgrade) UPGRADE_FLAG="--upgrade" ;;
        *) echo "Unknown arg: $arg" >&2; exit 1 ;;
    esac
done

echo "==> Ensuring pip-tools is installed..."
"$PYTHON" -m pip install --quiet --upgrade pip-tools

echo "==> Regenerating requirements-locked.txt with hashes..."
"$PYTHON" -m piptools compile \
    --generate-hashes \
    --resolver=backtracking \
    --output-file=requirements-locked.txt \
    $UPGRADE_FLAG \
    requirements.in

echo "==> Verifying lockfile is installable with --require-hashes..."
"$PYTHON" -m pip install --dry-run --require-hashes --quiet -r requirements-locked.txt

echo ""
echo "OK — requirements-locked.txt regenerated and verified."
echo "Commit requirements.in AND requirements-locked.txt together."
