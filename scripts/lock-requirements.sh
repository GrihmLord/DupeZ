#!/usr/bin/env bash
# Regenerate the runtime and unprivileged test locks with wheel hashes.
#
# Pins every direct and transitive dependency to reviewed wheel hashes so
# `pip install --require-hashes` can verify supply-chain integrity.
#
# Usage:
#     scripts/lock-requirements.sh           # regenerate
#     scripts/lock-requirements.sh --upgrade # bump to latest allowed

set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
UPGRADE_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --upgrade) UPGRADE_ARGS=(--upgrade) ;;
        *) echo "Unknown arg: $arg" >&2; exit 1 ;;
    esac
done

echo "==> Ensuring reviewed pip and pip-tools versions are installed..."
"$PYTHON" -m pip install --quiet --only-binary=:all: \
    "pip==26.2.2" "pip-tools==7.6.1"

new_reviewed_lock() {
    local input_path="$1"
    local output_path="$2"
    shift 2

    echo "==> Regenerating $output_path with hashes..."
    "$PYTHON" -m piptools compile \
        --generate-hashes \
        --resolver=backtracking \
        --strip-extras \
        --no-emit-options \
        --pip-args=--only-binary=:all: \
        --output-file="$output_path" \
        "${UPGRADE_ARGS[@]}" \
        "$@" \
        "$input_path"
    "$PYTHON" scripts/verify_requirements_lock.py \
        --requirements "$input_path" \
        --lock "$output_path"
    "$PYTHON" -m pip install --only-binary=:all: --dry-run \
        --require-hashes --quiet -r "$output_path"
}

new_reviewed_lock requirements.in requirements-locked.txt
new_reviewed_lock requirements-test.in requirements-test-locked.txt --allow-unsafe

echo ""
echo "OK — runtime and test locks regenerated and verified."
echo "Commit each requirements input together with its paired lock."
