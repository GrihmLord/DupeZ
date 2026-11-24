# Native release correspondence and IUP source input

Reviewed October 25, 2026. This is technical provenance evidence, not a license
approval, complete corresponding-source determination or release authorization.
The machine-readable results are in
`packaging/license-evidence/native-source-mapping-2026-10-25.json`.
The complete new local collection is recorded separately in
`packaging/license-evidence/source-input-collection-2026-10-25.json`.

All four files covered by `packaging/binary-provenance.json` match the inspected
Clumsy 0.3.4 release archive. IUP also matches its official Tecgraf package, and
the WinDivert DLL and driver match their official WinDivert 2.2.0-A package.
These comparisons used complete archive SHA-256/size verification followed by
bounded member reads and freshly hashed repository files. No downloaded code
was executed and no archive was extracted.

| Shipped file | Bytes | Independent official-package correspondence |
| --- | ---: | --- |
| `app/firewall/clumsy.exe` | 439,808 | `Clumsy.0.3.4.zip`, `Clumsy 0.3.4/clumsy.exe` |
| `app/firewall/iup.dll` | 2,744,320 | `iup-3.30_Win64_dll16_lib.zip`, `iup.dll`; also Clumsy release and source dependency |
| `app/firewall/WinDivert.dll` | 47,104 | `WinDivert-2.2.0-A.zip`, x64 DLL; also Clumsy release and source dependency |
| `app/firewall/WinDivert64.sys` | 90,288 | `WinDivert-2.2.0-A.zip`, x64 driver; also Clumsy release and source dependency |

The current Clumsy release tag resolves to
`bc87e73066168520d76122c9165e99ea703b166c`. Its `genie.lua` selects
`external/iup-3.30_Win64_dll16_lib` and `external/WinDivert-2.2.0-A` for VS x64
and copies the DLL/driver files from those packages. These source-tree bytes
also match the shipped files. The official IUP package description identifies
`dll16` as Visual Studio 2019 with a `VCRUNTIME140.DLL` dependency. It does not
identify the exact compiler servicing version, SDK, flags or complete build log.
[Clumsy build definition](https://github.com/kalirenegade-dev/clumsy/blob/bc87e73066168520d76122c9165e99ea703b166c/genie.lua),
[IUP platform descriptions](https://sourceforge.net/projects/iup/files/3.30/Windows%20Libraries/Dynamic/).

## Newly retained IUP input

Tecgraf identifies SourceForge as its official download location. The published
IUP 3.30 source ZIP was acquired and inspected under the same size/hash and
archive boundaries used for the other source inputs.
[Tecgraf download page](https://www.tecgraf.puc-rio.br/iup/en/download.html),
[official IUP 3.30 source digest](https://sourceforge.net/projects/iup/files/3.30/Docs%20and%20Sources/iup-3.30_Sources.zip/download).

- Filename: `iup-3.30_Sources.zip`
- Compressed bytes: **14,226,631**
- SHA-256: `92e1b56a6c78eeaca7cce3897536d333787e27e3ec25f94487dd0ab1d8d053e6`
- Inspection: **2,983 members**, **63,558,131 declared expanded bytes**, no links
- Retained source cache: `build/source-delivery-20261024/archives` (the new file
  was added; the earlier source ZIP and receipt were not overwritten)

`iup/include/iup.h` from the source archive is byte-for-byte identical to the
header in the official binary package and pinned Clumsy dependency. It declares
version 3.30 and date 2020/07/30. The header is 25,641 bytes with SHA-256
`d8759727c248b27f3d0ff2093265d1540b0129b532b57a37aaab6b3758dae24d`.

**The source archive was replaced on October 13, 2023, after the August 2020
binary package.** Header equality and the same version label cannot establish
the exact source revision or absence of later fixes. No source ZIP file has a
timestamp newer than August 2, 2020, but those timestamps are supporting
metadata, not a historical-source attestation. IUP's public build guide
describes Tecmake-based builds and bundled build scripts; that is guidance for
further rebuild work, not proof of how the shipped DLL was produced. An isolated
rebuild still needs the source/patch decision, toolchain and SDK inputs, build
configuration, build log and resulting DLL compatibility tests.
[Published archive dates](https://sourceforge.net/projects/iup/files/3.30/Docs%20and%20Sources/),
[IUP build guide](https://www.tecgraf.puc-rio.br/iup/en/guide.html).

## Cache acquisition and verification

SourceForge currently sends its stable archive URL through an expiring signed
mirror URL. **A fresh `collect` of IUP cannot follow that redirect.** The general
collector intentionally rejects redirects, query tokens and ambient proxies.
Its only URL exception permits the exact reviewed IUP 3.30 path's `%20` spaces;
arbitrary encoded paths, other versions, query strings and other origins remain
rejected. The 98-test source collector suite and Ruff checks passed.

The October 25 one-time acquisition inspected SourceForge's response, required
the exact HTTPS `master.dl.sourceforge.net` host and IUP file path, validated its
signed query field names, bounded the response to the upstream Content-Length,
and checked the independently published SHA-256 before the archive guard ran.
No expiring query tokens are retained. Recipients may acquire the official ZIP
through the upstream download page into a staging folder, then verify the exact
size/hash before adding it to their cache. Do not relax the collector's redirect
or hash requirements to make a fresh download appear successful.

From the retained reviewed cache, the current offline recipe is:

```powershell
$sourcePython = 'build/native-security-20261024/test-venv/Scripts/python.exe'
& $sourcePython scripts/corresponding_source.py plan
if ($LASTEXITCODE -ne 0) { throw 'Source plan failed' }

# Choose a fresh output path: receipts and bundles never overwrite old evidence.
& $sourcePython scripts/corresponding_source.py verify `
    --cache build/source-delivery-20261024/archives `
    --receipt build/source-delivery-20261025/source-input-recheck.json
if ($LASTEXITCODE -ne 0) { throw 'Source input verification failed' }
```

All 33 inventory components now have upstream version-source pins. The retained
compressed archives total **1,747,613,457 bytes**. This is input coverage, not a
claim that every native binary can already be reconstructed or that the source
has been publicly delivered. `plan --require-delivery-ready` continues to fail.

The full expanded collection was bundled and independently reverified:

- Bundle: `build/source-delivery-20261025/third-party-source-inputs.zip`
- Bundle bytes: **1,747,659,578**
- Bundle SHA-256: `b85370af421d6acbeb357d952f9663e0f270f35675cd1d686baa1fe76698023e`
- Collection and independent-verification receipts: **17,741 bytes** each,
  byte-identical, SHA-256
  `90dcf3dc9cf4f13540c9fc6d8f97792b1c5ee792091dcbc245352a07f2af8f4c`
- Embedded canonical manifest SHA-256:
  `b0cdf2c9121d117c393d13faac06935df0a1de4c311040926c56fcc2e3720b9f`

`verify-bundle --bundle build/source-delivery-20261025/third-party-source-inputs.zip`
rechecks the retained bundle against this manifest. The previous October 24
bundle and receipt were also rehashed and still match their dated record.

## Work still required

- Resolve exact IUP source revision/patches after the source archive replacement
  and independently record IUP and Clumsy native rebuilds and compatibility.
- Record an independent WinDivert source rebuild/replacement process and its
  driver-signing/installation constraints. Matching the signed upstream driver
  does not prove that a locally rebuilt driver will load or can be distributed.
- Finish the separate Qt/WebEngine wheel source, patch and toolchain mappings.
- Complete public source delivery/retention and the owner/legal-policy decisions.

The existing October 24 collection and recipient-build records remain dated
checkpoints. Their recorded limits are not erased by this additional evidence.
