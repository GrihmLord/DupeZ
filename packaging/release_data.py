"""Explicit PyInstaller data-file manifest for DupeZ releases."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath


HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "release-data.json"
MANIFEST_SCHEMA = "dupez.release-data.v1"


def release_data_files() -> tuple[str, ...]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if payload.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("unsupported release-data manifest schema")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("release-data manifest has no files")

    normalised: list[str] = []
    for value in files:
        if not isinstance(value, str):
            raise TypeError("release-data paths must be strings")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe release-data path: {value!r}")
        normalised.append(path.as_posix())
    if len(normalised) != len(set(normalised)):
        raise ValueError("release-data manifest contains duplicate paths")
    return tuple(normalised)


def pyinstaller_datas(root: str) -> list[tuple[str, str]]:
    root_path = Path(root).resolve()
    datas: list[tuple[str, str]] = []
    for relative in release_data_files():
        source = (root_path / PurePosixPath(relative)).resolve()
        if root_path not in source.parents or not source.is_file():
            raise FileNotFoundError(
                f"required release data file missing: {relative}"
            )
        destination = str(PurePosixPath(relative).parent).replace(
            "/",
            os.sep,
        )
        datas.append((str(source), destination))
    return datas
