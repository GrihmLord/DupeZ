# MSVC runtime package provenance review — 2026-11-09

The three MSVC runtime DLLs previously collected from System32 now match an exact official Microsoft redistributable package. This closes their upstream package identity gap. It does **not** establish the owner's Visual Studio entitlement, redistribution approval, complete native SBOM/notice delivery, or a native source rebuild.

## Verified package and file chain

Microsoft documents the versioned download route for releases 14.50 and later in its [redistributable troubleshooting guide](https://learn.microsoft.com/en-us/cpp/windows/troubleshoot-vc-redistributable-installation-issues?view=msvc-170). The exact 14.51.36247 x64 request resolved to this [Microsoft package](https://download.visualstudio.microsoft.com/download/pr/ebdab8e5-1d7b-4d9f-a11b-cbb1720c3b12/843068991DAAA1F73AD9F6239BCE4D0F6A07A51F18C37EA2A867E9BECA71295C/VC_redist.x64.exe).

- Package version: **14.51.36247.0**, 18,731,856 bytes.
- SHA256: `843068991daaa1f73ad9f6239bce4d0f6a07a51f18c37ea2a867e9beca71295c`.
- Authenticode: valid Microsoft Corporation signature, signer thumbprint `1D77A9B9E8FE2075D9AD15123257FB90DB0DA4A1`.
- Minimum-runtime MSI: product `{931A2CF0-2404-45EA-82F5-345735AE6A90}`, version `14.51.36247`.

The verifier reads the pinned PE's WiX Burn container ranges without loading the executable. It validates cabinet member names and sizes before using Windows' [expand command](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/expand) to extract selected files into a fresh workspace directory. The Burn manifest maps the minimum-runtime MSI and CAB to their signed package payloads. Read-only Windows Installer database queries then connect the CAB file keys to the MSI's file names, sizes, and versions. Microsoft describes this [CAB-to-File-table relationship](https://learn.microsoft.com/en-us/windows/win32/msi/cabinet-files).

| DLL | Size | SHA256 |
| --- | ---: | --- |
| `MSVCP140.dll` | 643,512 | `7c26614e1d733892c2deac7e245ce115504b1d80592dd0a01b08e3e5a55f89ca` |
| `MSVCP140_1.dll` | 35,768 | `206c931bf90fdad8816de3b5e2ef80b2bcaa9406c89ecc05fe6fddffe251e982` |
| `MSVCP140_2.dll` | 274,872 | `d50d7883f20d1dc6191768d3746f52dd9cac89c346ffaed5be1f110c2f34a838` |

All three DLLs match the prior System32 observation byte-for-byte and report version `14.51.36247.0`. Their Microsoft signatures are valid. The verifier rechecks the original inputs, every consumed extracted CAB/XML/MSI/DLL, and the extraction tool before publishing its receipt. It also checks the actual package byte snapshot used for parsing. The installer and DLLs are never executed; no global installation or UAC request occurs.

## License context and remaining owner decision

The package's own bootstrapper metadata links to [VCRedistLicense](https://aka.ms/VCRedistLicense). At review time this resolved to the [2026 runtime license page](https://visualstudio.microsoft.com/license-terms/vs2026-ga-visualcpp-v14-redist-runtime/) and its [English terms document](https://visualstudio.microsoft.com/wp-content/uploads/2025/10/Visual-C-V14-License-Redistributable_and_Runtime_ENU.docx). The document identifies `Cpp_v14_ENU.1033`, last updated October 1, 2025. Its SHA256 is `08651651a7602fc7c0e2763de0fde1ff9f868df2780597cd1775ee9d6441c783` (39,553 bytes). These standalone terms cover installation/use and restrict redistribution; they are not recorded as permission to redistribute DupeZ's bundled DLLs.

The separate [Visual Studio 2026 redistribution list](https://learn.microsoft.com/en-us/visualstudio/releases/2026/redistribution) permits the listed unmodified runtime files subject to a valid Visual Studio license and its applicable terms. Microsoft's [redistribution guidance](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files) applies that condition to individual runtime binaries as well as redistributable packages. A local Visual Studio installation, downloaded package, or valid signature does not establish the owner's qualifying license or its terms. That owner-specific basis remains unresolved; no licensing or release gate is approved by this review.

The package and license identities support a three-file native component mapping. They do not prove native compiler reconstruction, complete corresponding-source/relink obligations, project-wide notices, or vulnerability freedom. Any source/SBOM exception or additional permission must be established separately rather than inferred from these hashes.

## Reproduction and validation

Inputs are in [`packaging/msvc-redist-inputs.json`](../../packaging/msvc-redist-inputs.json). Download the pinned Microsoft package and license document into the workspace, verify their hashes, and invoke:

```powershell
python -I scripts/verify_msvc_redist.py `
  --package build/msvc-redist-provenance-20261109/VC_redist.x64.exe `
  --license-document build/msvc-redist-provenance-20261109/Visual-C-V14-License-Redistributable_and_Runtime_ENU.docx `
  --system-observation build/qt-raster-verified-final-20261109/system-runtime-observation.json `
  --output build/msvc-redist-provenance-20261109/new-verification
```

The previous System32 observation can be reconstructed from the corresponding public runtime evidence's recorded three-file observation; it is an input identity check, not a new host scan. The output directory must not already exist. The offline command requires Windows and standard-library Python; it uses inbox PowerShell, Windows Installer read-only database APIs, and `expand.exe`. The current signed CAB reserve/trailer layout is deliberately bounded; unsupported layouts are rejected.

The actual package verification passed. **53 tests passed**, including six inert mutation cases that replace extracted inputs or the tool during signature/MSI inspection and verify that no success receipt is published. Ruff passed. Earlier diagnostic runs exposed PowerShell module-path inheritance, DOCX formatting-run joining, and the signed CAB trailer; their failed logs are retained and are not labeled successful verification.

Machine-readable results and log/test identities are in [`msvc-redist-provenance-2026-11-09.json`](../../packaging/license-evidence/msvc-redist-provenance-2026-11-09.json). The prior frozen build/runtime records remain historical; this offline follow-up does not rerun them.
