# Qt software OpenGL helper: source review

Reviewed November 1, 2026, against repository checkpoint
`af461cbc899cf146d3d9808496a5806d75cb2528`. The Qt 6.11.3 candidate still carries
the **same Mesa/LLVM software OpenGL DLL as the Qt 6.11.2 baseline**. Updating
Qtbase therefore does not update this helper. The new evidence closes its
independent distribution mapping and retains upstream version-source inputs;
it does not establish a patched or independently rebuilt helper.

Machine-readable observations are in
[`qt-software-opengl-review-2026-11-01.json`](../../packaging/license-evidence/qt-software-opengl-review-2026-11-01.json).
All native inspection was performed on bytes. No downloaded DLL or archive
script was executed, and no runtime, production lock, source-delivery manifest
or owner/legal decision changed.

## Exact distribution correspondence

The following four observations contain byte-identical `opengl32sw.dll` files:

1. Qt's independently published signed software OpenGL prebuilt archive.
2. The pinned Qt 6.11.3 installer helper archive used by the candidate preparer.
3. The extracted Qt 6.11.3 candidate prefix.
4. The prior clean Qt 6.11.2 PyPI build environment.

The DLL is **20,639,888 bytes**, SHA256
`b04de4541863bc7d8879040a78889c4849c1b1da2784c4630f734c146c2998ce`.
The independent archive is **5,023,568 bytes**, SHA256
`c61f801c1760aa24b02c7a8354323cddf368b86f8f5c34b50b3b224f7d728afd`;
Qt publishes that size and digest in its
[archive metadata](https://download.qt.io/development_releases/prebuilt/llvmpipe/windows/opengl32sw-64-mesa_11_2_2-signed_sha256.7z.mirrorlist).
The differently compressed installer archive is **5,474,526 bytes**, SHA256
`f9a6f0229f63d04b3ec1cc455078171f4d0c32e4fd79bc3e6a6dca54e79f7eae`.
Both archives were freshly hashed before bounded member reads and direct byte
comparison. Each contains exactly one regular DLL member.

Windows Authenticode verification returned `Valid`, with signer The Qt Company
Oy. Static ASCII data identifies **Mesa 11.2.2** and **LLVM 3.6.2**. The x64 PE
timestamp is June 14, 2016; the signature/archive date is not evidence of a
newer Mesa source or security patch level. The PE import table names only
Windows DLLs. The embedded LLVM string and absent external LLVM import support
investigating LLVM as a bundled component, but do not prove its exact source
revision or compilation flags.

Qt's main download URL returned a redirect, which the review downloader
rejected. The successful acquisition used one exact HTTPS mirror URL listed
by Qt, with redirects and ambient proxies disabled, a fixed byte bound, and
Qt's independently published SHA256. The general source collector was not
relaxed.

## Retained source inputs and open correspondence gaps

The new inputs remain separate under
`build/qt-software-opengl-review-20261101/`. The existing 33-component source
bundle and its receipts remain unchanged.

| Source archive | Bytes | Verification and inspection |
| --- | ---: | --- |
| `mesa-11.2.2.tar.xz` | 7,860,932 | SHA256 matches the upstream release notes; 5,055 members, 75,105,294 expanded bytes |
| `llvm-3.6.2.src.tar.xz` | 12,802,380 | Official HTTPS archive size matches the index; locally hashed; detached signature retained but not verified; 16,463 members, 98,023,473 expanded bytes |

Mesa archive SHA256:
`40e148812388ec7c6d7b6657d5a16e2e8dabba8b97ddfceea5197947647bdfb4`.
Its `VERSION` member declares `11.2.2`. The license document, SCons entry point,
Windows libgl target and LLVM build integration members were individually
hashed. The [Mesa release notes](https://docs.mesa3d.org/relnotes/11.2.2.html)
publish the archive checksum, and the
[official archive directory](https://archive.mesa3d.org/older-versions/11.x/11.2.2/)
provides the source and signature.

Observed LLVM archive SHA256:
`f60dc158bfda6822de167e87275848969f0558b3134892ff54fced87e4667b94`.
Its CMake version declarations are `3`, `6`, `2`, and its license file was
individually hashed. The
[LLVM 3.6.2 directory](https://releases.llvm.org/3.6.2/) supplies the exact
archive size and a detached signature. **This review did not authenticate the
release signing key or verify that signature.** The observed digest is not
misrepresented as an independently published checksum. Complete that step
before promoting these LLVM bytes to a trusted build input.

Both archives passed bounded streaming inspection for safe relative member
paths, no links and no special files. Nothing was extracted to the filesystem.
These are version-source observations. Qt's current
[software OpenGL build guide](https://wiki.qt.io/index.php?title=MesaLlvmpipe&oldid=33647)
mentions additional patches and now describes newer Mesa/LLVM versions. It
does not supply an exact historical recipe for this DLL. The exact Qt patch
set, compiler servicing version, SDK, dependency versions, flags and build
log remain unresolved. Matching source version strings does not settle them.

The earlier Qtbase/Svg source-to-SPDX comparison applies to those Qt modules,
not to this separately shipped helper. Its recorded `.tag` discrepancies and
independent rebuild limits remain in the
[October 25 review](../audits/QT_NATIVE_REVIEW_2026-10-25.md).

## Runtime decision

Qt's [Windows graphics documentation](https://doc.qt.io/qt-6.11/windows-graphics.html)
describes `opengl32sw.dll` as the fallback for dynamically selected OpenGL.
`QT_OPENGL=software` explicitly requests this implementation when an OpenGL
context is needed. At this checkpoint,
`app/gui/map_host/renderer_tier.py` sets that value for frozen launches;
`dupez.py` also uses it in the renderer-policy exception fallback.

Repository text search found no application construction of `QOpenGLWidget`
or `QOpenGLWindow`. That is a useful reason to investigate a raster-only
packaged application, but does not prove that no dependency requests OpenGL.
Removing the DLL while leaving the current policy in place is therefore not
claimed safe. A change must first define a consistent raster-only policy,
then validate the full application and Compat normal/low-resource lifecycle
with the helper absent. Alternatively, retain it only with explicit source,
build, security and notice coverage. No removal, native rebuild, CVE
applicability clearance, Compat execution or release approval is asserted here.
