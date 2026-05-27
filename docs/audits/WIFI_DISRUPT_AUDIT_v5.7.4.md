# WiFi Disrupt Feature — Deep Audit

Date: 2026-05-26
Scope: `app/network/{arp_spoof, npcap_check, wifi_probe}.py`, `app/firewall/{target_profile, clumsy_network_disruptor, native_divert_engine}.py`, `app/utils/helpers.py`

## Executive summary

The WiFi same-network disrupt feature is structurally sound and the v5.6.4/5/v5.7.x patches did the hard work of removing silent no-ops at the policy layer (Npcap missing, ArpSpoofer.start() returning False, AP-isolation watchdog). The remaining defects are all in the **resource-cleanup-on-exception** and **opsec-in-logs** axes, plus untested fallback paths. Nothing is exploitable, but several paths leak Npcap handles / IP-forwarding state / poisoned ARP entries on exception, and the ArpSpoofer log line at start() prints the raw target and gateway IPs without masking. Test coverage stops at the spoofer's happy path — the isolation watchdog, the self-disrupt fallback, and the Npcap-check module have zero unit tests.

Verdict: **ship-ready for the happy path; harden before next release.** 4 HIGH, 6 MEDIUM, 5 LOW findings below, plus 7 architecture recommendations and 9 test-coverage gaps.

---

## HIGH findings

### H1 — `ArpSpoofer.start()` has no top-level exception guard; any raise leaks Npcap handle + IP forwarding state
**File:** `app/network/arp_spoof.py:854-964`
**Symptom:** If `NpcapSender.load()`, `NpcapSender.open()`, `_find_interface()` (which uses ctypes pcap_findalldevs), or any of the warmup `_poison_once()` calls raises an exception, `start()` propagates it to the caller. By that point we may have:
- Set IP forwarding ON (line 903) — never restored
- Loaded/opened the Npcap handle — never closed
- Set `self._running = True` (line 946) but no thread is started — `stop()` will run partial cleanup
- Allocated a Linux AF_PACKET socket — never closed

The caller in `clumsy_network_disruptor.py:1365-1374` catches the exception and sets `_arp_spoofer = None`, dropping the only reference to the leaked resources. `NpcapSender` has no `__del__`, so the pcap handle leaks until process exit.

**Fix:** wrap `start()` body in a try/except that calls `_cleanup_partial()` (a new helper that closes sender, closes linux_sock, calls `_restore_forwarding`, and resets `_running=False`) before re-raising or returning False.

### H2 — Linux ARP socket bind failure is a silent no-op
**File:** `app/network/arp_spoof.py:921-939`
**Symptom:** The Linux raw-socket path resolves the interface name via `ip -o addr show` and binds the AF_PACKET socket. If the interface lookup fails (`iface` is None), the code logs a debug message but **does not return False** — `start()` continues to the warmup burst with an unbound raw socket. Sends will go out the default interface or raise; the spoofer will report success while the target is unaffected. This is exactly the silent-no-op pattern v5.6.4 was supposed to eliminate.

**Fix:** if `iface` is None on Linux, `_restore_forwarding()` and `return False`.

### H3 — Raw target IP and gateway IP logged unmasked at start()
**File:** `app/network/arp_spoof.py:873-874, 887, 895`
**Lines:**
```python
log_info(f"ArpSpoofer: target={self.target_ip}, gateway={self.gateway_ip}")
log_error(f"ArpSpoofer: cannot resolve MAC for target {self.target_ip} — ...")
log_error(f"ArpSpoofer: cannot resolve MAC for gateway {self.gateway_ip}")
```
The disruptor masks every IP it logs, but `arp_spoof.py` does not import `mask_ip` and emits the full quads. Anyone with log access (shared logging service, support bundle, GH issue paste) sees the operator's home subnet and gateway in plaintext.

**Fix:** `from app.utils.helpers import mask_ip`, wrap every `target_ip`/`gateway_ip` interpolation. Also `_mac_from_arp_windows({ip})` (line 366), `_mac_from_arp_linux({ip})` (line 381), and `get_mac_for_ip({ip})` (line 305).

### H4 — `IsolationWatchdog` logs raw `self._target_ip` and Npcap MAC addresses unmasked
**File:** `app/network/wifi_probe.py:284, 296, 306`, plus thread name on line 233
**Lines:**
```python
name=f"IsolationWatchdog[{self._target_ip}]"
log_info(f"[WiFi-WATCHDOG] target={self._target_ip} OK — ...")
```
Thread names appear in `ps`/Task Manager and exception tracebacks. The arp_spoof log lines also print MAC addresses (`local MAC = {mac}`, `target MAC = {mac}`, `gateway MAC = {mac}`) at lines 881-882, 889-890, 897-898 — those identify the target's vendor and uniquely identify the device.

**Fix:** mask IP in watchdog logs (`mask_ip(self._target_ip)`) and consider a `mask_mac()` helper in `app/utils/helpers.py` (e.g. `aa:bb:cc:**:**:**`). MACs leak even worse than IPs because they're stable across sessions.

---

## MEDIUM findings

### M1 — ARP cache restoration never runs on process crash
**File:** `app/network/arp_spoof.py:1081-1110`
**Symptom:** Restore happens only via `stop()`. If the process is `kill -9`'d or hits SIGSEGV (likely on a ctypes bug), the target's ARP cache stays poisoned pointing at our MAC for the gateway. Once the laptop disconnects, the target's traffic to the gateway black-holes for 30-60s until the ARP entry ages out. Worse on endpoints that pin ARP under load.

**Fix:** register an `atexit.register(spoofer.stop)` from the disruptor when the spoofer starts. Also consider catching SIGINT/SIGTERM in the main app to trigger graceful shutdown. The atexit handler is best-effort but covers the common "operator closes the window" path.

### M2 — `_is_wifi_same_network` hardcodes /24 prefix
**File:** `app/firewall/target_profile.py:221`
**Lines:**
```python
local_net = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
return addr in local_net
```
Many home/office networks use /23 or /22 (especially Eero mesh, business APs). A target on `192.168.2.10` won't be detected as same-network when the operator is on `192.168.1.50/23`. The detection falls through to "outside hotspot and local subnet → NETWORK (local)" which opens NETWORK layer pointed at the wrong target → silent no-op.

**Fix:** read the actual interface netmask via `psutil.net_if_addrs()[iface][n].netmask` and use that. Fall back to /24 only when the netmask isn't available.

### M3 — Watchdog cancel-vs-fire race not fully closed
**File:** `app/network/wifi_probe.py:250-311`, `app/firewall/clumsy_network_disruptor.py:1573-1582`
**Symptom:** `reconnect_device_clumsy` calls `wd.cancel()` (sets event) then `engine.stop()`. The watchdog thread can be past its cancellation check and into the counter-read phase when cancel() lands. It then calls `_on_result(ISOLATION_DETECTED)` which calls `_fallback_to_self_disrupt`. The fallback defends with a "device already released" check (line 1717), so the user-visible damage is limited to a misleading toast — but the fallback could also race with a concurrent `disrupt_device(target_ip)` (operator re-disrupts the same target immediately) and tear down the new engine.

**Fix:** in `_fire`, check `_cancelled` once more before calling `_on_result`. Tighten the device-lock window in `_fallback_to_self_disrupt` to atomically read `info` AND verify the engine reference matches the one the watchdog was armed with (compare object identity, not just dict presence).

### M4 — Watchdog thread not joined; orphan window of up to 250ms
**File:** `app/network/wifi_probe.py:226-235`, `app/firewall/clumsy_network_disruptor.py:1573-1578`
**Symptom:** `wd.cancel()` doesn't wait for the watchdog thread to exit. Until the thread polls the cancel event (max 0.25s), it holds references to the spoofer, engine, and `_on_result` callback (which closes over `self` of the disruptor). Daemon=True so the process can exit, but during operation it's a brief reference leak. Bigger issue: in `_fallback_to_self_disrupt`, the watchdog could fire AFTER we've started building the new engine, leading to confusion.

**Fix:** add a `join(timeout=1.0)` after `cancel()`, log a warning if it didn't exit.

### M5 — `clear_all_disruptions_clumsy` swallows per-device errors
**File:** `app/firewall/clumsy_network_disruptor.py:1831-1836`
```python
def clear_all_disruptions_clumsy(self) -> bool:
    with self._device_lock:
        ips = list(self.disrupted_devices.keys())
    for ip in ips:
        self.reconnect_device_clumsy(ip)
    return True
```
Returns True unconditionally even if individual reconnects fail (and the function does return False on engine.stop() exception, M3 above). Callers can't tell if cleanup left orphan engines.

**Fix:** aggregate results, return `all(success)`.

### M6 — `NpcapSender` lacks `__del__` / context-manager protocol
**File:** `app/network/arp_spoof.py:599-813`
**Symptom:** If a partial init fails (load() returned True, open() raised), nothing closes the handle. GC won't help — ctypes handles aren't tracked. Compounds H1.

**Fix:** add `__enter__/__exit__` so the spoofer can use `with NpcapSender() as sender:` semantics, OR add `__del__` that calls `close()` defensively.

---

## LOW findings / nits

### L1 — `_get_ip_forwarding_state()` returns on the first line containing "forwarding"
**File:** `app/network/arp_spoof.py:533-535`
The Windows netsh output has multiple lines with "forwarding" depending on locale. Currently the function returns the verdict from the first match. On localized Windows this could parse "Forwarding Configuration" → no "enabled" → False even when forwarding is on.

**Fix:** look for "IP Forwarding" specifically, or use the Win32 API (`GetIpForwardTable2`) for an OS-level read.

### L2 — `ArpSpoofer` constructor does not validate `target_ip`
**File:** `app/network/arp_spoof.py:833-835`
A malformed `target_ip` propagates through to `arp -a`, `ping`, and socket.connect. Operator gets a generic "cannot resolve MAC for target" error after 3+ subprocess invocations.

**Fix:** `ipaddress.IPv4Address(target_ip)` at construction; raise `ValueError` with a clear message.

### L3 — `_poison_loop` swallows every exception with generic `log_error`
**File:** `app/network/arp_spoof.py:1068-1080`
If `_poison_once` raises consistently (e.g. Npcap handle died), the loop logs every iteration but never exits or self-terminates. Operator sees a healthy `_running=True` while every frame fails.

**Fix:** count consecutive send failures; if N (e.g. 5) in a row, log a CRITICAL error, set `_running=False`, and let the disruptor's flow-health watchdog surface the situation.

### L4 — `IsolationWatchdog._on_result` callback runs on the watchdog thread; orchestrator state mutation needs the lock
**File:** `app/firewall/clumsy_network_disruptor.py:1663-1675`
The docstring says "caller is responsible for any thread-safety on shared state". `_fallback_to_self_disrupt` does take `self._device_lock` correctly, but it's a non-obvious requirement. Future contributors will forget.

**Fix:** add a one-line comment at the top of `_fallback_to_self_disrupt` that explicitly states "runs on watchdog thread; all reads/writes of disrupted_devices MUST hold _device_lock".

### L5 — `_kill_all_clumsy` and `taskkill /F /IM clumsy.exe` swallow all errors
**File:** `app/firewall/clumsy_network_disruptor.py:326-348`, `app/firewall/native_divert_engine.py:731-744`
Bare `except Exception: pass`. If taskkill is missing (rare but possible on minimal Windows images), or fails for a permission reason, we silently proceed and may end up with two clumsy.exe instances. Low impact because WinDivert serializes anyway, but the diagnostic message would be welcome.

**Fix:** log at `log_warning` level on taskkill failure.

---

## Verified-OK invariants

These were checked and are correct — no need to re-audit:

1. **safe_subprocess** prevents shell injection across every Windows binary call (`netsh`, `arp`, `ipconfig`, `route`, `taskkill`, `ping`). `target_ip` flows in as an isolated argv token; even malformed inputs cannot escape the argv array.
2. **WinDivert filter validation** (`validate_filter_string` in `app/core/validation.py`) is an allowlist tokenizer applied in `NativeWinDivertEngine.__init__`. Both the WiFi path filter and the self-disrupt fallback filter go through it.
3. **`mask_ip`** in `app/utils/helpers.py` is used consistently across the disruptor's user-facing log lines (lines 1189, 1202, 1318, 1325, 1450, 1554, 1558, 1591, 1595, 1598, 1673, 1694, 1719, 1733, 1795, 1803, 1825).
4. **WinDivert layer selection** when ARP spoof activates correctly forces `is_local = False` / `_network_local = False` (lines 1331-1333). The v5.6.4 honest-abort path on `_npcap.available is False` (line 1297) and on `ArpSpoofer.start()` returning False (line 1343) both `return False` instead of silently downgrading. Watchdog also correctly skips `clumsy.exe` fallback engines (line 1543-1551).
5. **Detection result → preset mapping** correctly forces `_network_local` from `_detection.layer` (lines 1245-1256). Operator can override with `_force_self_disrupt` (line 1230).
6. **`packets_sent` accessor** is lock-protected on both read and write (lines 1003-1007, 1022-1024).
7. **ctypes restypes** on `NpcapSender.load()` are correctly declared as `c_void_p` for pcap_open_live (the historical bug call-out is in the docstring at line 624-629).
8. **Loopback/link-local guards** in `_is_wifi_same_network` (target_profile.py:212-213) and the fallback in `detect_wifi_same_network` (arp_spoof.py:438) prevent ARP spoof attempts on 127.x or 169.254.x addresses.
9. **DPI / kernel module checks** in NativeWinDivertEngine.start (`compute_file_integrity` on WinDivert.dll and WinDivert64.sys, lines 768-774) catch tampered drivers before they're loaded.

---

## Test coverage gaps

Priority-ordered:

1. **`IsolationWatchdog` end-to-end** — no test file exists for `app/network/wifi_probe.py`. Need tests for: (a) WORKING when `_packets_processed>0` after grace, (b) ISOLATION_DETECTED when sent>0 processed==0, (c) INCONCLUSIVE when both zero, (d) ABORTED when cancel() fires mid-grace, (e) ABORTED when engine._running flips False during grace, (f) callback runs exactly once even on concurrent cancel + fire race. (HIGH priority — security-critical fallback decision.)
2. **`_fallback_to_self_disrupt`** — entirely untested. Need: (a) early-abort when device already released, (b) toast emitted before teardown, (c) new engine on NETWORK layer with `_wifi_self_disrupt=True`, (d) failure to restart pops device + emits error toast, (e) old spoofer + engine stop() exceptions don't abort the restart.
3. **`ArpSpoofer.start()` exception cleanup** — H1. Need: (a) Npcap.load() raise → forwarding restored, sender None'd; (b) Npcap.open() raise → forwarding restored, load handle closed; (c) warmup `_poison_once` raise → all of the above + thread not started.
4. **Linux ARP socket bind failure path** — H2. Need a test that monkeypatches `_get_raw_socket` to return a socket and forces iface lookup to fail; assert `start()` returns False AND forwarding is restored.
5. **`npcap_check.check_npcap`** — no tests. Need: Windows path (DLL present at each of 4 candidate paths), Windows missing path, Linux root, Linux non-root.
6. **`target_profile.resolve_target_profile` WiFi-same-net branch** — only `_is_wifi_same_network` is reachable via integration. Need direct tests asserting `needs_arp_spoof=True`, `layer="forward"`, and `connection_mode==CONNECTION_MODE_WIFI_SAME_NET` for a same-WiFi target.
7. **Watchdog cancellation race** — M3. Need a deterministic test that interleaves the cancel and the counter-read using threading.Event barriers.
8. **`clear_all_disruptions_clumsy` error propagation** — M5. Need: one engine raises on stop, assert `clear_all` returns False (after the fix).
9. **ARP cache restoration on stop()** — verify the right number of restore frames sent with the right MAC pairs (test currently checks count > prev only). Tighten to assert frame[28:32] == gateway_ip + sender_mac == real gateway_mac.

---

## Architecture recommendations

1. **Move resource ownership into a context manager.** `ArpSpoofer` should be usable as `with ArpSpoofer(target_ip=...) as spoofer: ...` — `__exit__` runs `stop()` unconditionally. Eliminates the entire class of "exception during start leaks resources" bugs (H1, M6).
2. **Add `mask_mac()` to `app/utils/helpers.py`.** Format: keep OUI (first 3 octets — vendor identification is already public via OUI database), mask the device-unique trailing 3 octets. Apply to every MAC log statement in arp_spoof.py and wifi_probe.py.
3. **Add `atexit.register(stop)` to the disruptor.** Best-effort ARP cache cleanup on process termination (M1). Pair with a SIGINT handler.
4. **Replace the `_is_wifi_same_network` /24 hardcoding** with actual interface netmask reads (M2). This is the most likely source of "doesn't work on my LAN" support tickets.
5. **Introduce a `WifiDisruptSession` orchestration class** that owns the spoofer, engine, watchdog, and detection state as one unit. Replace the current `disrupted_devices[ip] = {"engine": ..., "arp_spoofer": ..., "wifi_watchdog": ..., ...}` dict-of-dicts. Cleaner ownership semantics, easier to mock in tests, makes H1's fix obvious.
6. **Hot-reload guard for ARP cache state.** On disruptor `initialize()`, check if IP forwarding is already enabled and the local arp cache contains entries that look like ours (e.g. local MAC pointing to non-local IPs). If so, the previous session didn't shut down cleanly — log a warning and offer to flush.
7. **Replace the daemon-thread-with-event-cancellation pattern** (used by both `ArpSpoofer._poison_loop` and `IsolationWatchdog`) with `concurrent.futures.Future` or a cancellable `asyncio` task. The current pattern works but is hard to reason about under composition (M3, M4).

---

## What's NOT broken — short list

If a future audit asks "what's the actual ROI of this code?" — these are the things that work and shouldn't be touched:

- v5.6.4 silent-no-op abort logic (Npcap missing, spoof start fails).
- v5.6.5/v5.7.2 isolation watchdog as a separate observer that doesn't mutate engine state — clean separation of concerns.
- Direction-aware modules forcing `direction="both"` on the WiFi path (lines 1278-1291) — correct, because ARP spoof capture is asymmetric and presets default to inbound-only.
- The hot-path target_ip u32 precompute in `NativeWinDivertEngine.__init__` — zero-allocation packet direction detection on the FORWARD layer.
- Subprocess hardening via `safe_subprocess` everywhere except the deliberate `subprocess.Popen` for the long-lived clumsy.exe child.

---

## Closing assessment

The WiFi disrupt feature does what it claims, and the policy layer is honest about its failure modes. The structural risk is on the **resource-cleanup edges** — a single ctypes raise inside ArpSpoofer.start() will leak handles and forwarding state until process restart, and the user has no diagnostic for it. The opsec risk is the unmasked IPs and MACs in arp_spoof.py and wifi_probe.py logs — easy to fix, easy to forget.

Recommended sequence: H3 + H4 (logging masks, ~1h), H1 + H2 + M6 (cleanup context manager, ~3h), M2 (netmask detection, ~2h), test coverage gaps 1-5 (~6h), then ship. Architecture items 1, 5, 7 are next-quarter refactors.
