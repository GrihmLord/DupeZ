# Defender Release Trust Audit - 2026-07-01

## Official guidance reviewed

- Microsoft Security Intelligence accepts submissions for files that are
  incorrectly classified as malware/PUA. The portal supports software
  developer submissions and asks for detection name, Defender definition
  version, business impact, and platform context:
  https://www.microsoft.com/en-us/wdsi/filesubmission
- Microsoft Defender for Endpoint guidance starts false-positive handling by
  identifying the detection source before applying a remedy:
  https://learn.microsoft.com/en-us/defender-endpoint/defender-endpoint-false-positives-negatives
- Microsoft SignTool guidance says modern SDKs require explicit file digest
  and timestamp digest options, recommends SHA-256, and documents `/tr`,
  `/td`, and `/fd` for timestamped Authenticode signing:
  https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool

## Decisions applied

1. Keep Defender enabled. DupeZ diagnostics may read local Defender posture,
   but must not add exclusions, disable real-time protection, or mutate
   Defender policy.
2. Ship transparent builds. UPX is disabled for PyInstaller outputs because
   packed privileged bundles with packet-driver binaries are harder for
   endpoint tools to classify and easier to false-positive.
3. Sign all release executables when `DUPEZ_SIGN_CERT` is configured:
   `DupeZ-GPU.exe`, `DupeZ-Compat.exe`, the versioned installer, and
   `DupeZ_Setup.exe`.
4. Require timestamped SHA-256 Authenticode commands in release preflight:
   `/tr`, `/td sha256`, and `/fd sha256`.
5. For true false positives, submit the specific blocked artifact to Microsoft
   Security Intelligence with the Defender detection name and definition
   version instead of asking users to create broad exclusions.

## Follow-up release checklist

- Build from a clean tree using non-UPX PyInstaller specs.
- Run `python scripts/release_preflight.py --version <version> --dist`.
- Run `python scripts/defender_release_check.py --scan` on the Windows
  release machine before uploading artifacts.
- Verify Authenticode signatures on all distributed `.exe` files.
- Verify `packaging/binary-provenance.json` for bundled WinDivert/clumsy
  binaries.
- If Defender blocks a clean signed artifact, submit only the blocked file to
  Microsoft as "incorrectly detected" and include the detection name.
