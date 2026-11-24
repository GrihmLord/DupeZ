"""Fail-closed entry point for compiling the release installer.

This wrapper exists so the batch pipeline cannot invoke ISCC against the mutable
native staging directory.  ``release_data.compile_installer`` owns verification,
snapshotting, compiler environment setup, and snapshot cleanup.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# ``python -I path\to\script.py`` deliberately omits the script directory
# from sys.path.  The canonical batch driver uses isolated mode, so resolve the
# sibling module from this reviewed directory explicitly instead of depending
# on cwd, PYTHONPATH, or ambient site customizations.
_PACKAGING_DIR = str(Path(__file__).resolve().parent)
sys.path.insert(0, _PACKAGING_DIR)
try:
    from release_data import compile_installer
finally:
    sys.path.remove(_PACKAGING_DIR)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True)
    parser.add_argument("--iscc", required=True)
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[1]
    compile_installer(
        repository_root,
        expected_mode=args.mode,
        iscc=args.iscc,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
