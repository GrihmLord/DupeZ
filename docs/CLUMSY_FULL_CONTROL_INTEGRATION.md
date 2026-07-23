# Clumsy Keybind Edition 0.3.4 — DupeZ Full-Control Contract

This document is the release contract for the bundled Kalirenegade Clumsy
Keybind Edition 0.3.4 binary. The binary is pinned in
`packaging/binary-provenance.json`; behavior and bounds below are grounded in
the pinned source commit recorded there.

## Safety invariant for the top filter

The DupeZ field is named **Additional filter** and defaults to `true`.

`true` means **no additional narrowing**. It never becomes the complete
WinDivert expression. DupeZ always generates an immutable exact-target scope:

```text
ip.SrcAddr == <authorized-private-target>
or ip.DstAddr == <authorized-private-target>
```

A non-`true` user predicate is parenthesized and ANDed with that mandatory
scope. Newlines, record delimiters, comments, quotes, slashes, semicolons,
unbalanced parentheses, public targets, and attempts to close the outer scope
are rejected before `config.txt` is written.

## User-facing control mapping

The consolidated **Smart Ops → Clumsy Advanced Controls** panel supplies the
settings not already represented by the existing effect sliders.

| Fork control | DupeZ control / parameter | Contract |
|---|---|---|
| Filtering text | Additional filter / `_clumsy_filter_predicate` | Defaults to `true`; target scope cannot be replaced |
| Filter preset name | `_clumsy_filter_name` | One sanitized config record, maximum 48 characters |
| Network Local / Remote | Event Capture Layer | Verified IUP combobox callback |
| Function Presets | `_clumsy_function_preset_name` | Selected from the generated five-entry preset list |
| Trigger Toggle / Timer | `_clumsy_trigger_mode` | Toggle or Timer |
| Timer value | `_clumsy_timer_seconds` | Integer 1–60 seconds; manager generation cleanup remains authoritative |
| Lag | `lag`, `lag_delay` | Delay 0–15000 ms |
| Drop | `drop`, `drop_chance` | Chance 0–100% |
| Disconnect | `disconnect` | Fixed full disconnect; no chance/timing approximation |
| Bandwidth Limiter | `bandwidth_queue`, `bandwidth_limit`, `bandwidth_size` | Queue/limit 0–99999; KB/s or MB/s |
| Throttle | `throttle_frame`, `throttle_chance`, `throttle_drop` | Frame 0–1000 ms; chance 0–100%; Drop Throttled callback verified |
| Duplicate | `duplicate_count`, `duplicate_chance` | DupeZ exposes 1–49 additional copies; fork receives 2–50 total |
| Out of order | `ood_chance` | Chance 0–100% |
| Tamper | `tamper_chance`, `tamper_checksum` | Chance 0–100%; Redo Checksum callback verified |
| Set TCP RST | `rst_chance` | Chance 0–100% |
| RST next packet | `_clumsy_rst_next_packet` or authenticated live action | Requires a live owned Clumsy process with Set TCP RST enabled; one eligible TCP packet consumes the one-shot |
| Per-row Inbound / Outbound | `<module>_direction` | Each enabled module independently supports both, inbound, or outbound |
| Start / Stop | Owned process lifecycle | Start must transition visibly to Stop; stop is graceful before exact-PID fallback |

## End-to-end routing

The same parameter map is used by:

1. Manual **DISRUPT** actions.
2. Smart Ops recommendations.
3. Saved and ordered event queues.
4. Compat/in-process architecture.
5. GPU/elevated-helper architecture.

The advanced adapter runs first, then the event adapter adds explicit
engine/capture-layer routing. Temporary routing metadata is removed from a
Smart Ops recommendation object after execution so recommendations remain
reusable.

## Runtime verification

Direct Clumsy startup must verify, in order:

1. Exact owned process and top-level window.
2. Complete Functions control tree.
3. Local/Remote network callback.
4. Every requested top-level module toggle.
5. Function preset callback.
6. Per-module Inbound/Outbound callbacks.
7. Drop Throttled / Redo Checksum callbacks when applicable.
8. KB/s / MB/s control when Bandwidth Limiter is active.
9. Toggle / Timer controls and Timer value.
10. Every requested numeric EDIT through `WM_SETTEXT` plus the IUP-consumed
    `WM_COMMAND / EN_CHANGE` callback.
11. Start-to-Stop transition.
12. Optional RST-next one-shot after Start.

Any missing or unconfirmed control fails explicit Clumsy closed. Auto can use
Native only when the requested semantics remain equivalent.

## Required evidence before release

- Complete pytest suite on Python 3.11 and 3.12.
- Authorized source-mode hardware matrix against one exact private IP/MAC.
- No orphaned `clumsy.exe` process after normal or failed runs.
- Generated `config.txt` / `presets.ini` restored after tests.
- GPU and Compat frozen executables both pass `--verify-runtime-imports`.
- Frozen archive preflight contains the complete integration modules and no
  unfinished social packages or forbidden optional dependencies.
- Diagnostic-window restoration verified in both frozen variants.
- Normal and forced low-resource startup/shutdown verified.
- Installer, Authenticode/RFC3161, Defender, SBOM/VEX/provenance, and signed
  updater-manifest gates completed before merge, tag, or publication.
