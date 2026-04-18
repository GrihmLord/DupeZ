"""
One-shot migration helper: sign already-trained model artefacts.

Before :mod:`app.core.model_integrity` landed, model ``.pkl`` files
were written with a bare ``pickle.dump`` and loaded with a bare
``pickle.load``. Loading an untrusted ``.pkl`` is RCE. The new
inference loaders refuse any artefact without a sibling ``.hmac``.

Use this script **once**, on a trusted workstation, to produce the
``.hmac`` for each pre-existing artefact after you've verified its
integrity yourself (e.g. by confirming it came from a known-good
training run on a machine you control).

Usage::

    python -m scripts.sign_models                      # sign default paths
    python -m scripts.sign_models app/data/models/a.pkl path/b.pkl
    python -m scripts.sign_models --verify             # only verify, don't sign

Returns non-zero exit on any failure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

from app.core.model_integrity import (
    ModelIntegrityError,
    is_signed,
    load_artefact,
    sign_existing_artefact,
)

_DEFAULT_PATHS = [
    Path("app/data/models/duration_regressor.pkl"),
    Path("app/data/models/survival_model.pkl"),
]


def _sign_one(path: Path, force: bool) -> bool:
    if not path.exists():
        print(f"[skip] {path}: does not exist")
        return True
    if is_signed(path) and not force:
        print(f"[skip] {path}: already signed")
        return True
    try:
        tag = sign_existing_artefact(path)
    except ModelIntegrityError as e:
        print(f"[FAIL] {path}: {e}", file=sys.stderr)
        return False
    print(f"[ok]   {path}: {tag[:16]}…")
    return True


def _verify_one(path: Path) -> bool:
    if not path.exists():
        print(f"[skip] {path}: does not exist")
        return True
    try:
        load_artefact(path)
    except ModelIntegrityError as e:
        print(f"[FAIL] {path}: {e}", file=sys.stderr)
        return False
    print(f"[ok]   {path}: verified")
    return True


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scripts.sign_models")
    ap.add_argument("paths", nargs="*", type=Path,
                    help="Artefact paths (default: standard model locations).")
    ap.add_argument("--verify", action="store_true",
                    help="Verify-only; do not write any .hmac file.")
    ap.add_argument("--force", action="store_true",
                    help="Re-sign even when a .hmac already exists.")
    args = ap.parse_args(argv)

    paths = args.paths or _DEFAULT_PATHS
    ok = True
    for p in paths:
        if args.verify:
            ok &= _verify_one(p)
        else:
            ok &= _sign_one(p, args.force)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
