from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import pytest

from app.core import model_integrity


_TEST_KEY = b"model-integrity-test-key-32-byte"


@pytest.fixture(autouse=True)
def _fixed_integrity_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model_integrity, "_get_key", lambda: _TEST_KEY)


def _write_valid_tag(path: Path, data: bytes) -> str:
    tag = hmac.new(_TEST_KEY, data, hashlib.sha384).hexdigest()
    Path(f"{path}.hmac").write_text(tag, encoding="utf-8")
    return tag


def _forbid_unpickling(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(_data: bytes) -> object:
        pytest.fail("pickle.loads reached before model HMAC verification")

    monkeypatch.setattr(model_integrity.pickle, "loads", fail_if_called)


def test_load_verifies_hmac_before_unpickling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artefact = tmp_path / "model.pkl"
    data = b"authenticated-model-payload"
    artefact.write_bytes(data)
    expected_tag = _write_valid_tag(artefact, data)

    events: list[tuple[str, bytes]] = []
    real_verify = model_integrity._verify
    loaded = object()

    def tracked_verify(candidate: bytes, expected: str) -> bool:
        events.append(("verify", candidate))
        assert expected == expected_tag
        return real_verify(candidate, expected)

    def tracked_loads(candidate: bytes) -> object:
        assert events == [("verify", data)]
        events.append(("loads", candidate))
        return loaded

    monkeypatch.setattr(model_integrity, "_verify", tracked_verify)
    monkeypatch.setattr(model_integrity.pickle, "loads", tracked_loads)

    assert model_integrity.load_artefact(artefact) is loaded
    assert events == [("verify", data), ("loads", data)]


def test_missing_integrity_tag_never_reaches_unpickling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artefact = tmp_path / "model.pkl"
    artefact.write_bytes(b"unsigned-model-payload")
    _forbid_unpickling(monkeypatch)

    with pytest.raises(model_integrity.ModelIntegrityError, match="missing integrity tag"):
        model_integrity.load_artefact(artefact)


@pytest.mark.parametrize(
    ("tag", "message"),
    [
        ("short", "integrity tag length mismatch"),
        ("g" * 96, "integrity tag mismatch"),
        ("0" * 96, "integrity tag mismatch"),
    ],
    ids=("wrong-length", "non-hex", "wrong-digest"),
)
def test_invalid_integrity_tag_never_reaches_unpickling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tag: str,
    message: str,
) -> None:
    artefact = tmp_path / "model.pkl"
    artefact.write_bytes(b"model-payload")
    Path(f"{artefact}.hmac").write_text(tag, encoding="utf-8")
    _forbid_unpickling(monkeypatch)

    with pytest.raises(model_integrity.ModelIntegrityError, match=message):
        model_integrity.load_artefact(artefact)


def test_tampered_artefact_never_reaches_unpickling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artefact = tmp_path / "model.pkl"
    original = b"original-authenticated-model"
    artefact.write_bytes(original)
    _write_valid_tag(artefact, original)
    artefact.write_bytes(b"tampered-model-payload")
    _forbid_unpickling(monkeypatch)

    with pytest.raises(model_integrity.ModelIntegrityError, match="integrity tag mismatch"):
        model_integrity.load_artefact(artefact)
