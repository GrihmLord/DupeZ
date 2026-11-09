"""Isolated, standard-user QWidget probe with six GL/helper binaries absent.

This does not modify a wheel, installed environment, release profile or renderer
policy. Its derived import tree is a probe fixture, not an installable artifact.
Run with a Python that has pefile; --python names the isolated child interpreter.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WHEEL_SHA256 = "5ae71fb933f4cafeaba3eac2d98a35ece588950ea34d3fa5e0252cbc811b29a9"
SIP_SHA256 = "ca24bfd4d5d8274e338433df9ac41930650088c00018d3313c6bd8de21772a02"
REMOVED = frozenset({
    "PyQt6/QtOpenGL.pyd", "PyQt6/QtOpenGLWidgets.pyd",
    "PyQt6/Qt6/bin/Qt6OpenGL.dll", "PyQt6/Qt6/bin/Qt6OpenGLWidgets.dll",
    "PyQt6/Qt6/bin/opengl32sw.dll", "PyQt6/Qt6/bin/d3dcompiler_47.dll",
})


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(data, indent=2) + "\n")


def loaded_modules(site: Path, expected: dict) -> tuple[list[dict], list[str]]:
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.K32EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE),
                                          wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel.K32EnumProcessModules.restype = wintypes.BOOL
    kernel.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetModuleFileNameW.restype = wintypes.DWORD
    handles = (wintypes.HMODULE * 2048)()
    needed = wintypes.DWORD()
    require(bool(kernel.K32EnumProcessModules(kernel.GetCurrentProcess(), handles,
                 ctypes.sizeof(handles), ctypes.byref(needed))), "Cannot enumerate child modules")
    require(needed.value <= ctypes.sizeof(handles), "Module enumeration exceeded bound")
    forbidden = {Path(name).name.casefold() for name in REMOVED}
    result = []
    system_graphics = []
    for handle in handles[:needed.value // ctypes.sizeof(wintypes.HMODULE)]:
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetModuleFileNameW(handle, buffer, len(buffer))
        require(0 < length < len(buffer), "Cannot resolve module path")
        path = Path(buffer.value).resolve()
        require(path.name.casefold() not in forbidden, "Removed native member was loaded")
        if path.name.casefold() in {"opengl32.dll", "d3d9.dll", "d3d11.dll", "d3d12.dll", "dxgi.dll", "vulkan-1.dll"}:
            system_graphics.append(path.name.casefold())
        if (path.name.casefold().startswith("qt6")
                or any(part.casefold() == "pyqt6" for part in path.parts)):
            require(path.is_relative_to(site), "Qt module loaded outside the derived probe tree")
            member = path.relative_to(site).as_posix()
            require(member in expected and digest(path) == expected[member], "Native hash mismatch")
            result.append({"member": member, "sha256": expected[member]})
    return sorted(result, key=lambda row: row["member"]), sorted(system_graphics)


def child(out: Path) -> None:
    site = (out / "site").resolve()
    inventory = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    expected = inventory["native_sha256"]
    for member, sha256 in expected.items():
        require(digest(site / member) == sha256, "Derived native hash mismatch")
    require(all(not (site / member).exists() for member in REMOVED), "Excluded native is present")
    sys.path.insert(0, str(site))
    from PyQt6.QtCore import QByteArray, QCoreApplication, Qt, qVersion
    from PyQt6.QtGui import QColor, QImage, QPainter, QSurface
    from PyQt6.QtSvgWidgets import QSvgWidget
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import (QApplication, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

    require(qVersion() == "6.11.3", "Unexpected Qt version")
    require(os.environ.get("QT_OPENGL") == "software", "Existing GL fallback policy was changed")
    for name in ("QtOpenGL", "QtOpenGLWidgets"):
        require(importlib.util.find_spec("PyQt6." + name) is None, "Excluded binding is importable")
    QCoreApplication.setLibraryPaths([str(site / "PyQt6/Qt6/plugins")])
    app = QApplication([])
    require(app.platformName() == "windows", "Native Windows platform was not selected")
    card_path = ROOT / "app/gui/widgets/collapsible_card.py"
    require(digest(card_path) == inventory["application_widget_sha256"], "Application widget changed")
    card_spec = importlib.util.spec_from_file_location("raster_probe_card", card_path)
    card_module = importlib.util.module_from_spec(card_spec)
    card_spec.loader.exec_module(card_module)
    window = QWidget()
    window.setWindowTitle("DupeZ isolated raster runtime probe")
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    layout = QVBoxLayout(window)
    label = QLabel("Trusted local raster content")
    label.setTextFormat(Qt.TextFormat.PlainText)
    layout.addWidget(label)
    table = QTableWidget(2, 2)
    table.setItem(0, 0, QTableWidgetItem("rendered"))
    card = card_module.CollapsibleCard("Local test card", table)
    layout.addWidget(card)
    button = QPushButton("Probe action")
    button.clicked.connect(lambda: label.setText("Clicked"))
    layout.addWidget(button)
    svg = QSvgWidget()
    svg.load(QByteArray(b'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">'
                       b'<rect width="32" height="32" fill="#bc2846"/></svg>'))
    svg.setFixedSize(32, 32)
    layout.addWidget(svg)
    window.resize(480, 260)
    window.show()
    QTest.qWait(150)
    require(window.windowHandle().surfaceType() == QSurface.SurfaceType.RasterSurface,
            "Widget window is not a raster surface")
    require(not window.grab().isNull(), "Native window capture failed")
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    require(label.text() == "Clicked", "Widget input did not dispatch")
    table.setCurrentCell(0, 0)
    require(table.currentItem().text() == "rendered", "Table selection failed")
    card.set_expanded(False)
    require(not card.expanded and table.isHidden(), "Application card did not collapse")
    card.set_expanded(True)
    require(card.expanded and not table.isHidden(), "Application card did not expand")
    image = QImage(32, 32, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    svg.render(painter)
    painter.end()
    require(image.pixelColor(16, 16).getRgb() == (188, 40, 70, 255), "SVG pixel mismatch")
    observations, system_graphics = loaded_modules(site, expected)
    window.close()
    app.processEvents()
    require(not window.isVisible(), "Widget did not close")
    app.quit()
    write_json(out / "runtime.json", {
        "status": "passed", "qt_version": qVersion(), "platform": app.platformName(),
        "elevated": False, "qt_opengl": os.environ["QT_OPENGL"],
        "surface_type": "RasterSurface", "widget_capture": True, "button_input": True,
        "table_selection": True, "svg_center_rgba": [188, 40, 70, 255], "clean_close": True,
        "application_collapsible_card_toggle": True,
        "application_widget_sha256": inventory["application_widget_sha256"],
        "excluded_bindings_not_importable": True, "loaded_native_members": observations,
        "removed_native_members_loaded": [], "loaded_system_graphics_basenames": system_graphics,
    })


def prepare(args: argparse.Namespace) -> None:
    import pefile

    spec = importlib.util.spec_from_file_location("candidate", ROOT / "scripts/prepare_qt_candidate.py")
    candidate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)
    out = candidate.ordinary_path(args.output, missing=True)
    require(out.is_relative_to(ROOT / "build"), "Probe output must be inside workspace build/")
    require(not out.exists(), "Probe output already exists; choose a fresh directory")
    source = candidate.ordinary_path(args.candidate_root)
    wheel = source / "wheel/PyQt6-6.11.0-6.11.3dupezcandidate-cp310-abi3-win_amd64.whl"
    sip = source / "inputs/pyqt6_sip-13.11.1-cp313-cp313-win_amd64.whl"
    python = candidate.ordinary_path(args.python, file=True)
    require(digest(wheel) == WHEEL_SHA256 and digest(sip) == SIP_SHA256, "Reviewed wheel hash mismatch")
    out.mkdir(parents=True)
    native = {}
    removed = []
    for archive_path in (wheel, sip):
        candidate.inspect_wheel(archive_path)
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                member = info.filename
                if not member.startswith("PyQt6/") or info.is_dir():
                    continue
                data = archive.read(info)
                sha256 = hashlib.sha256(data).hexdigest()
                if member in REMOVED:
                    removed.append({"member": member, "sha256": sha256, "size": len(data)})
                    continue
                if (member in {"PyQt6/QtOpenGL.pyi", "PyQt6/QtOpenGLWidgets.pyi"}
                        or member.startswith(("PyQt6/bindings/QtOpenGL/", "PyQt6/bindings/QtOpenGLWidgets/"))):
                    continue
                target = out / "site" / member
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as handle:
                    handle.write(data)
                if target.suffix.casefold() in {".dll", ".pyd"}:
                    native[member] = sha256
    require({row["member"] for row in removed} == REMOVED, "Expected exclusion set mismatch")
    forbidden = {Path(member).name.casefold() for member in REMOVED}
    imports = []
    for member in sorted(native):
        with pefile.PE(str(out / "site" / member), fast_load=False) as pe:
            dependencies = sorted({row.dll.decode("ascii").casefold()
                                   for key in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
                                   for row in getattr(pe, key, [])})
        require(not (forbidden & set(dependencies)), "Remaining native binary imports an excluded binary")
        imports.append({"member": member, "imports_and_delay_imports": dependencies})
    write_json(out / "inventory.json", {
        "schema": "dupez.qt-raster-runtime-probe.v1", "observed_at": datetime.now(timezone.utc).isoformat(),
        "script_sha256": digest(Path(__file__)), "source_wheel_sha256": WHEEL_SHA256,
        "sip_wheel_sha256": SIP_SHA256, "derived_tree_is_installable_artifact": False,
        "application_widget_sha256": digest(ROOT / "app/gui/widgets/collapsible_card.py"),
        "native_sha256": native, "removed_native_members": removed, "pe_import_review": imports,
        "removed_native_bytes": sum(row["size"] for row in removed),
    })
    env = candidate.child_environment(out / "private")
    env.update({"QT_QPA_PLATFORM": "windows", "QT_OPENGL": "software"})
    with (out / "runtime.log").open("xb") as log:
        result = subprocess.run([str(python), "-I", str(Path(__file__).resolve()), "--child", str(out)],
                                cwd=out, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=60, check=False)
    require(result.returncode == 0, "Child failed; inspect runtime.log")
    print(json.dumps({"status": "passed", "native_members": len(native), "removed_native_members": len(removed),
                      "removed_native_bytes": sum(row["size"] for row in removed), "output": str(out)}))


def main() -> None:
    require(sys.platform == "win32", "Windows-only probe")
    require(not ctypes.windll.shell32.IsUserAnAdmin(), "Standard-user token required")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--candidate-root", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.child:
        child(args.child)
    else:
        require(all((args.candidate_root, args.python, args.output)), "All three paths are required")
        prepare(args)


if __name__ == "__main__":
    main()
