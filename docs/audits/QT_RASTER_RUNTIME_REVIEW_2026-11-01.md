# Isolated Qt raster runtime review — November 1, 2026

The Qt 6.11.3 candidate passed a bounded native Windows widget probe with
`opengl32sw.dll`, `d3dcompiler_47.dll`, both OpenGL binding extensions and both
OpenGL Qt libraries absent. This is evidence for investigating a smaller
runtime. **It is not adoption of that profile or clearance to remove these
files from production.** Production Qt 6.11.2, the reviewed candidate profile,
renderer policy and dependency locks remain unchanged.

The reproducible probe is
[`scripts/probe_qt_raster_runtime.py`](../../scripts/probe_qt_raster_runtime.py).
The committed
[machine-readable evidence](../../packaging/license-evidence/qt-raster-runtime-review-2026-11-01.json)
contains native hashes, all remaining normal/delay import tables, runtime
observations and exact limitations. The application checkpoint inspected was
`1b6017245886d795a1a84e1b01b7b1e5d689854e`.

## What the existing renderer settings mean

Source inspection found no application imports or construction of the
OpenGL bindings, `QOpenGLWidget`, `QOpenGLWindow`, Qt Quick or pyqtgraph.
The custom splash painting uses `QPainter`; the dashboard panels use native
Qt widgets. This search alone cannot establish all transitive behavior.

Qt documents its raster engine as the default for `QWidget` and `QPixmap`,
and always used for drawing to `QImage`. Drawing with `QPainter` therefore
does not by itself imply OpenGL use.
[Qt QPainter performance documentation](https://doc.qt.io/qt-6.11/qpainter.html#performance).

The current frozen policy sets `QT_OPENGL=software`; the bootstrap exception
fallback also sets it. Qt describes this as selecting the software OpenGL
implementation when OpenGL is used. It is not a switch that makes ordinary
widgets use the raster paint engine. This probe retained that value: changing
it to `desktop` or removing it would introduce a different renderer decision
and was unnecessary for the observed widget success.
[Qt Windows graphics documentation](https://doc.qt.io/qt-6.11/windows-graphics.html).

## Inputs and exclusions

The probe extracts a new private import tree from these exact wheels. It
does not edit either source wheel, installed venv, candidate manifest or
distribution metadata. It copies no `.dist-info` and is explicitly **not an
installable or distributable wheel**.

| Input | SHA256 |
| --- | --- |
| Reviewed Qt 6.11.3 restricted PyQt6 wheel | `5ae71fb933f4cafeaba3eac2d98a35ece588950ea34d3fa5e0252cbc811b29a9` |
| PyQt6 sip 13.11.1 CPython 3.13 wheel | `ca24bfd4d5d8274e338433df9ac41930650088c00018d3313c6bd8de21772a02` |

Six native members, totaling **28,077,416 uncompressed bytes**, were omitted:

| Member | Bytes |
| --- | ---: |
| `PyQt6/QtOpenGL.pyd` | 1,140,224 |
| `PyQt6/QtOpenGLWidgets.pyd` | 69,632 |
| `PyQt6/Qt6/bin/Qt6OpenGL.dll` | 1,988,408 |
| `PyQt6/Qt6/bin/Qt6OpenGLWidgets.dll` | 65,336 |
| `PyQt6/Qt6/bin/opengl32sw.dll` | 20,639,888 |
| `PyQt6/Qt6/bin/d3dcompiler_47.dll` | 4,173,928 |

The corresponding two binding stub files and binding definition directories
were omitted as well. All 34 remaining native files (33 candidate members
plus sip) match their original wheel bytes. None of their normal or delay
import tables references the six excluded binaries. This statement does not
cover runtime `LoadLibrary` or equivalent dynamic selection.

## Observed native Windows behavior

The final run used CPython 3.13.17 with a standard-user token, Qt 6.11.3,
`QT_QPA_PLATFORM=windows`, `QT_OPENGL=software`, a private profile/temp tree
and a minimal child environment. It did not use the offscreen plugin.

The probe passed window creation and capture, mouse dispatch to a button,
table selection, SVG rendering with an exact expected center pixel, and
window close. It also loaded the actual
`app/gui/widgets/collapsible_card.py` source file by verified hash and passed
collapse/expand checks. It did not import the dashboard, controller or
startup pipeline.

The window reported `QSurface::RasterSurface`, which Qt defines as a pixel
surface suitable for its raster paint engine.
[Qt QSurface documentation](https://doc.qt.io/qt-6.11/qsurface.html#SurfaceType-enum).
All 15 loaded Qt, plugin and sip modules matched the retained wheel hashes
inside the new import tree. Neither excluded binding was importable, and
none of the six excluded native basenames was loaded.

Windows `d3d9.dll`, `d3d11.dll`, `d3d12.dll` and `dxgi.dll` were nevertheless
loaded. The retained QtGui and Windows platform plugin import graphics APIs.
A raster widget result does not mean the process contains no graphics
libraries. No OpenGL context was requested or hardware rendering validated.

Raw final evidence is retained under
`build/qt-raster-runtime-final-20261101/`; its inventory, runtime JSON and
empty successful runtime log hashes are recorded in the committed evidence.
Ruff passed for the probe script. An earlier run without the application card
also passed; the committed results refer only to the final expanded probe.

Additional source inspection found that `app/main.py` unconditionally enables
`Qt.ApplicationAttribute.AA_ShareOpenGLContexts` before constructing
`QApplication`, with a comment explaining the WebEngine requirement. This
probe did not enable that attribute or execute the real startup path. Its
success therefore does not establish that the application's shared-context
startup works without the software OpenGL helper. Review whether this
attribute is needed for the frozen browser-excluded profile, then test that
exact startup path before adopting any helper removal.

## Conservative next implementation

1. Define an explicit frozen raster-widget profile and review its inherited
   environment policy. In particular, Qt documents `QT_OPENGL_DLL` as an
   alternate OpenGL implementation path. The existing `QT_OPENGL=software`
   assignment does not itself neutralize that override. This probe's minimal
   environment does not test ambient rendering overrides, bug lists or
   widget RHI settings.
2. After completing the startup assessment, create a separately named candidate wheel
   with a reviewed exclusion manifest, regenerated/validated RECORD and
   exact retained-byte mapping. Add packaging and final-archive rejection
   checks for the six excluded binaries and both excluded bindings, rather
   than deleting files from an installed runtime.
3. Validate full source tests and clean frozen GPU/Compat builds against that
   precise new profile. Run both normal and low-resource lifecycle checks,
   map fallback, shared-context startup/splash, optional plugin import coverage, actual
   Compat elevation and relevant display/remote-session configurations.
4. Update native/source inventories only for artifacts actually rebuilt with
   the new profile. Preserve historical Mesa source gaps for older payloads.

`QOpenGLContext` remains exposed through the retained `QtGui` module, and the
retained native libraries still support graphics APIs. Excluding the two
OpenGL bindings does not disable every way to request a GL context. A future
feature or plugin could create one, so the packaging policy and full runtime
tests must define how unsupported paths fail before reduction is adopted.

No packet effects, game operations, network requests, elevation, Compat
execution, native security clearance, source rebuild correspondence,
licensing approval or release approval is asserted by this probe. Existing
[software OpenGL source gaps](../legal/QT_SOFTWARE_OPENGL_SOURCE_REVIEW_2026-11-01.md)
remain applicable to both unchanged production and reviewed candidate
payloads.
