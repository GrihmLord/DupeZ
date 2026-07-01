"""
Regression tests for the DayZ account tracker CSV/XLSX import path.

The bug fixed in app/gui/dayz_account_tracker.py had four root causes:

  1. _XLSX_DEFAULT_FIELDS was missing the 'value' column → positional
     mapping was off-by-one for headerless files.
  2. encoding='utf-8' did not strip the UTF-8 BOM that Excel-exported
     CSVs include → the first header was un-mappable → every row was
     silently dropped.
  3. The header-synonym map was thin: aliases like 'character',
     'server', 'kit', 'role', 'inv', 'tier' and tag-prefixed forms
     like '#email' / '@notes' were not recognised.
  4. There was no delimiter sniffing → semicolon- and tab-delimited
     CSVs were parsed as a single-column table.

These tests exercise the canonicalisation + parsing helpers without
spinning up the full Qt GUI. We import the module under a stub-Qt
namespace so it loads on any host.
"""

from __future__ import annotations

import sys
import types

import pytest


# ── Stub PyQt6 + supporting app modules so the GUI file imports ──────

@pytest.fixture(scope="module", autouse=True)
def _qt_stubs():
    qt = types.ModuleType("PyQt6")
    qt_widgets = types.ModuleType("PyQt6.QtWidgets")
    qt_core = types.ModuleType("PyQt6.QtCore")
    qt_gui = types.ModuleType("PyQt6.QtGui")

    class _Stub:
        def __init__(self, *a, **kw): pass
        def __getattr__(self, k): return _Stub()
        def __call__(self, *a, **kw): return _Stub()

    for name in ("QWidget", "QApplication", "QInputDialog", "QDialog",
                 "QVBoxLayout", "QHBoxLayout", "QLabel", "QLineEdit",
                 "QPushButton", "QTableWidget", "QTableWidgetItem",
                 "QHeaderView", "QFileDialog", "QMessageBox", "QComboBox",
                 "QFrame", "QSplitter", "QListWidget", "QListWidgetItem",
                 "QProgressDialog", "QMenu", "QAction", "QSizePolicy",
                 "QPlainTextEdit", "QSpinBox", "QDoubleSpinBox",
                 "QGroupBox", "QFormLayout", "QGridLayout", "QStyle",
                 "QStyledItemDelegate", "QAbstractItemView", "QToolButton"):
        setattr(qt_widgets, name, _Stub)
    for name in ("Qt", "QSize", "QTimer", "pyqtSignal", "QPoint",
                 "QRegularExpression", "QObject", "QEvent", "QRect"):
        setattr(qt_core, name, _Stub)
    for name in ("QColor", "QIcon", "QFont", "QPixmap", "QBrush",
                 "QPainter", "QStandardItemModel", "QStandardItem",
                 "QShortcut", "QKeySequence", "QAction"):
        setattr(qt_gui, name, _Stub)

    sys.modules.setdefault("PyQt6", qt)
    sys.modules.setdefault("PyQt6.QtWidgets", qt_widgets)
    sys.modules.setdefault("PyQt6.QtCore", qt_core)
    sys.modules.setdefault("PyQt6.QtGui", qt_gui)
    yield


def _load_tracker_helpers():
    """Import only the non-Qt helpers from the tracker module via AST.

    The full module imports the application Qt graph; we extract just
    the helper symbols we want to test by parsing the file and
    exec'ing the relevant top-level statements in a controlled
    namespace.
    """
    import ast
    import pathlib

    src = pathlib.Path("app/gui/dayz_account_tracker.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)

    # Keep: imports for stdlib, Assigns for the constants/dicts we need,
    # FunctionDef for the helpers we care about. Drop everything else.
    keep_names = {
        "ACCOUNT_FIELDS", "STATUS_OPTIONS", "STATION_OPTIONS",
        "DAYZ_MAP_OPTIONS", "NEEDS_FILTER_OPTIONS", "VALUE_FILTER_OPTIONS",
        "_NO_NEEDS_VALUES", "_LOW_VALUE_MARKERS", "_MEDIUM_VALUE_MARKERS",
        "_HIGH_VALUE_MARKERS",
        "_XLSX_KNOWN_HEADERS", "_XLSX_DEFAULT_FIELDS",
        "_STATUS_CANON", "_STATION_CANON",
        "_normalize_header", "_canon_status", "_canon_station",
        "_account_text_blob", "_infer_dayz_map", "_has_open_needs",
        "_value_bucket", "_filter_dayz_accounts",
    }
    new_body = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            # Drop app.* and PyQt6.* imports — we substitute them.
            if mod.startswith("app.") or mod.startswith("PyQt6"):
                continue
            new_body.append(node)
        elif isinstance(node, ast.Import):
            new_body.append(node)
        elif isinstance(node, ast.Assign):
            tgts = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if tgts & keep_names:
                new_body.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id in keep_names:
                new_body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in keep_names:
            new_body.append(node)

    tree.body = new_body
    ast.fix_missing_locations(tree)
    ns: dict = {"__name__": "tracker_helpers", "__builtins__": __builtins__}
    code = compile(tree, "dayz_account_tracker_helpers", "exec")
    exec(code, ns)
    return ns


@pytest.fixture(scope="module")
def tracker():
    return _load_tracker_helpers()


# ── Header normalisation ──────────────────────────────────────────────

def test_normalize_strips_bom(tracker):
    assert tracker["_normalize_header"]("\ufeffEmail") == "email"


def test_normalize_strips_tag_prefix(tracker):
    assert tracker["_normalize_header"]("#account") == "account"
    assert tracker["_normalize_header"]("@email") == "email"
    assert tracker["_normalize_header"](":notes") == "notes"


def test_normalize_collapses_separators(tracker):
    assert tracker["_normalize_header"]("Server-Location") == "server location"
    assert tracker["_normalize_header"]("server_location") == "server location"
    assert tracker["_normalize_header"]("Server.Location") == "server location"


def test_normalize_lowercases_and_trims(tracker):
    assert tracker["_normalize_header"]("  ACCOUNT  ") == "account"
    assert tracker["_normalize_header"]("MIxedCase") == "mixedcase"


def test_normalize_handles_none_and_blank(tracker):
    assert tracker["_normalize_header"](None) == ""
    assert tracker["_normalize_header"]("") == ""
    assert tracker["_normalize_header"]("   ") == ""


# ── Header synonym map ────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected_field", [
    ("character", "account"),
    ("char", "account"),
    ("handle", "account"),
    ("gamer tag", "account"),
    ("server", "location"),
    ("region", "location"),
    ("kit", "station"),
    ("role", "station"),
    ("class", "station"),
    ("inv", "holding"),
    ("loadout", "loadout"),
    ("weapons", "loadout"),
    ("tier", "value"),
    ("priority", "value"),
    ("comment", "notes"),
    ("description", "notes"),
])
def test_synonyms_resolve(tracker, raw, expected_field):
    norm = tracker["_normalize_header"](raw)
    assert tracker["_XLSX_KNOWN_HEADERS"][norm] == expected_field


# ── Status / station canonicalisation ─────────────────────────────────

def test_canon_status_normalises_case(tracker):
    canon = tracker["_canon_status"]
    options = tracker["STATUS_OPTIONS"]
    # Every known status must round-trip from upper / lower / mixed.
    for opt in options:
        assert canon(opt.lower()) == opt
        assert canon(opt.upper()) == opt


def test_canon_status_passes_unknown_through(tracker):
    canon = tracker["_canon_status"]
    assert canon("totally made up") == "totally made up"


def test_canon_station_normalises_case(tracker):
    canon = tracker["_canon_station"]
    options = tracker["STATION_OPTIONS"]
    for opt in options:
        assert canon(opt.lower()) == opt


# ── Defaults sanity ───────────────────────────────────────────────────

def _sample_accounts():
    return [
        {
            "account": "Main",
            "location": "Chernarus - Tisy",
            "status": "Ready",
            "station": "Geared",
            "gear": "Plate Carrier",
            "holding": "LAR and NVGs",
            "loadout": "LAR",
            "needs": "Ammo",
            "value": "High",
            "notes": "north route",
        },
        {
            "account": "Mule",
            "location": "Livonia bunker",
            "status": "Storage",
            "station": "Raider Kit",
            "gear": "Backpack",
            "holding": "Building supplies",
            "loadout": "BK",
            "needs": "-",
            "value": "Medium",
            "notes": "",
        },
        {
            "account": "Fresh",
            "location": "Coast",
            "status": "Dead",
            "station": "",
            "gear": "",
            "holding": "",
            "loadout": "",
            "needs": "Everything",
            "value": "Low",
            "notes": "Sakhal restart",
        },
    ]


def test_infer_dayz_map_from_location_or_notes(tracker):
    infer = tracker["_infer_dayz_map"]
    accounts = _sample_accounts()

    assert infer(accounts[0]) == "Chernarus"
    assert infer(accounts[1]) == "Livonia"
    assert infer(accounts[2]) == "Sakhal"


def test_open_needs_detection(tracker):
    has_open_needs = tracker["_has_open_needs"]
    accounts = _sample_accounts()

    assert has_open_needs(accounts[0]) is True
    assert has_open_needs(accounts[1]) is False


def test_value_bucket_detection(tracker):
    bucket = tracker["_value_bucket"]
    accounts = _sample_accounts()

    assert bucket(accounts[0]) == "High Value"
    assert bucket(accounts[1]) == "Medium Value"
    assert bucket(accounts[2]) == "Low Value"


def test_dayz_filter_combines_facets(tracker):
    filt = tracker["_filter_dayz_accounts"]
    accounts = _sample_accounts()

    result = filt(
        accounts,
        status="Ready",
        station="Geared",
        map_name="Chernarus",
        needs_state="Needs Work",
        value_bucket="High Value",
        search_text="lar",
    )

    assert [a["account"] for a in result] == ["Main"]


def test_dayz_filter_no_needs_and_map(tracker):
    filt = tracker["_filter_dayz_accounts"]
    accounts = _sample_accounts()

    result = filt(accounts, map_name="Livonia", needs_state="No Needs")

    assert [a["account"] for a in result] == ["Mule"]


def test_xlsx_default_fields_matches_account_fields(tracker):
    """Off-by-one bug guard: positional mapping must use FULL field set."""
    defaults = tracker["_XLSX_DEFAULT_FIELDS"]
    fields = list(tracker["ACCOUNT_FIELDS"])
    assert defaults == fields, (
        "positional mapping field list must equal ACCOUNT_FIELDS — "
        "any drift here is the off-by-one regression that dropped 'value'"
    )
