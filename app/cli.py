# app/cli.py — DupeZ CLI Mode
"""
Headless terminal interface for DupeZ.

Usage:
    python -m app.cli scan                          # Quick network scan
    python -m app.cli scan --full                   # Full network scan
    python -m app.cli disrupt <ip> [--methods drop,lag] [--params '{"drop_chance":50}']
    python -m app.cli stop <ip>                     # Stop disruption on IP
    python -m app.cli stop --all                    # Stop all disruptions
    python -m app.cli status                        # Show engine status
    python -m app.cli devices                       # List known devices
    python -m app.cli plugins                       # List plugins
    python -m app.cli update --check                # Check for updates
"""

import os
import sys
import json
import argparse
import ctypes

# Ensure we can import app modules
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

from app.logs.logger import log_info, log_startup, log_shutdown

def _check_admin() -> bool:
    if os.name != 'nt':
        return os.geteuid() == 0 if hasattr(os, 'geteuid') else True
    return hasattr(ctypes, 'windll') and ctypes.windll.shell32.IsUserAnAdmin() != 0

def _print_banner():
    print("""
 ██████╗ ██╗   ██╗██████╗ ███████╗███████╗
 ██╔══██╗██║   ██║██╔══██╗██╔════╝╚══███╔╝
 ██║  ██║██║   ██║██████╔╝█████╗    ███╔╝
 ██║  ██║██║   ██║██╔═══╝ ██╔══╝   ███╔╝
 ██████╔╝╚██████╔╝██║     ███████╗███████╗
 ╚═════╝  ╚═════╝ ╚═╝     ╚══════╝╚══════╝
 v4.0.0 — CLI Mode
""")

def cmd_scan(controller, args):
    """Scan network for devices."""
    print("[*] Scanning network...")
    quick = not args.full
    devices = controller.scan_devices(quick=quick)
    if not devices:
        print("[!] No devices found")
        return

    print(f"\n[+] Found {len(devices)} device(s):\n")
    print(f"  {'IP':<18} {'MAC':<20} {'Hostname':<25} {'Vendor'}")
    print(f"  {'─'*18} {'─'*20} {'─'*25} {'─'*20}")
    for d in devices:
        ip = d.get('ip', '') if isinstance(d, dict) else d.ip
        mac = d.get('mac', '') if isinstance(d, dict) else d.mac
        hostname = d.get('hostname', 'Unknown') if isinstance(d, dict) else d.hostname
        vendor = d.get('vendor', '') if isinstance(d, dict) else d.vendor
        print(f"  {ip:<18} {mac:<20} {hostname:<25} {vendor}")

def cmd_disrupt(controller, args):
    """Start disruption on a target IP."""
    if not args.ip:
        print("[!] Usage: dupez cli disrupt <ip> [--methods drop,lag] [--params '{...}']")
        return

    methods = args.methods.split(",") if args.methods else None
    params = json.loads(args.params) if args.params else None

    print(f"[*] Starting disruption on {args.ip}...")
    if methods:
        print(f"    Methods: {', '.join(methods)}")
    if params:
        print(f"    Params: {params}")

    success = controller.disrupt_device(args.ip, methods, params)
    if success:
        print(f"[+] Disruption active on {args.ip}")
    else:
        print(f"[!] Failed to start disruption on {args.ip}")

def cmd_stop(controller, args):
    """Stop disruption."""
    if args.all:
        print("[*] Stopping all disruptions...")
        controller.stop_all_disruptions()
        print("[+] All disruptions cleared")
    elif args.ip:
        print(f"[*] Stopping disruption on {args.ip}...")
        success = controller.stop_disruption(args.ip)
        if success:
            print(f"[+] Disruption stopped on {args.ip}")
        else:
            print(f"[!] Failed to stop disruption on {args.ip}")
    else:
        print("[!] Usage: dupez cli stop <ip> or dupez cli stop --all")

def cmd_status(controller, args):
    """Show engine status."""
    clumsy_status = controller.get_clumsy_status()
    disrupted = controller.get_disrupted_devices()
    stats = controller.get_engine_stats()

    print("[*] Engine Status:\n")
    print(f"  Clumsy initialized: {clumsy_status.get('initialized', False)}")
    print(f"  Clumsy running:     {clumsy_status.get('running', False)}")
    print(f"  Active disruptions: {len(disrupted)}")

    if disrupted:
        print(f"\n  Disrupted IPs:")
        for ip in disrupted:
            status = controller.get_disruption_status(ip)
            methods = status.get('methods', []) if status else []
            print(f"    {ip} — methods: {', '.join(methods) if methods else 'default'}")

    if stats:
        print(f"\n  Packet Stats:")
        for key, val in stats.items():
            print(f"    {key}: {val}")

def cmd_devices(controller, args):
    """List known devices."""
    devices = controller.get_devices()
    if not devices:
        print("[!] No devices cached. Run 'scan' first.")
        return

    print(f"[+] {len(devices)} known device(s):\n")
    for d in devices:
        ip = d.ip if hasattr(d, 'ip') else d.get('ip', '')
        hostname = d.hostname if hasattr(d, 'hostname') else d.get('hostname', '')
        blocked = d.blocked if hasattr(d, 'blocked') else d.get('blocked', False)
        status = "BLOCKED" if blocked else "ok"
        print(f"  {ip:<18} {hostname or 'Unknown':<25} [{status}]")

def cmd_plugins(controller, args):
    """List plugins."""
    info = controller.get_plugin_info()
    if not info:
        print("[*] No plugins found in plugins/ directory")
        return

    print(f"[+] {len(info)} plugin(s):\n")
    print(f"  {'Name':<20} {'Version':<10} {'Type':<12} {'Status':<10} Description")
    print(f"  {'─'*20} {'─'*10} {'─'*12} {'─'*10} {'─'*30}")
    for p in info:
        status = "active" if p['active'] else ("error" if p.get('error') else "inactive")
        print(f"  {p['name']:<20} {p['version']:<10} {p['type']:<12} {status:<10} {p['description'][:40]}")

def cmd_interactive(controller, args):
    """Interactive REPL mode."""
    _print_banner()
    print("Type 'help' for commands, 'exit' to quit.\n")

    while True:
        try:
            cmd = input("dupez> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[*] Bye.")
            break

        if not cmd:
            continue
        if cmd in ("exit", "quit", "q"):
            break
        if cmd == "help":
            print("  scan [--full]              Scan network")
            print("  devices                    List known devices")
            print("  disrupt <ip> [methods]     Start disruption")
            print("  stop <ip> | stop --all     Stop disruption")
            print("  status                     Engine status")
            print("  plugins                    List plugins")
            print("  exit                       Quit")
            continue

        # Parse the interactive command
        parts = cmd.split()
        subcmd = parts[0]

        if subcmd == "scan":
            ns = argparse.Namespace(full="--full" in parts)
            cmd_scan(controller, ns)
        elif subcmd == "devices":
            cmd_devices(controller, argparse.Namespace())
        elif subcmd == "disrupt" and len(parts) >= 2:
            methods = parts[2] if len(parts) > 2 else None
            ns = argparse.Namespace(ip=parts[1], methods=methods, params=None)
            cmd_disrupt(controller, ns)
        elif subcmd == "stop":
            if "--all" in parts:
                cmd_stop(controller, argparse.Namespace(all=True, ip=None))
            elif len(parts) >= 2:
                cmd_stop(controller, argparse.Namespace(all=False, ip=parts[1]))
            else:
                print("[!] Usage: stop <ip> or stop --all")
        elif subcmd == "status":
            cmd_status(controller, argparse.Namespace())
        elif subcmd == "plugins":
            cmd_plugins(controller, argparse.Namespace())
        else:
            print(f"[!] Unknown command: {subcmd}. Type 'help' for commands.")

def main():
    parser = argparse.ArgumentParser(
        prog="dupez-cli",
        description="DupeZ CLI — headless network disruption tool"
    )
    subparsers = parser.add_subparsers(dest="command")

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan network for devices")
    p_scan.add_argument("--full", action="store_true", help="Full scan (slower, more thorough)")

    # disrupt
    p_disrupt = subparsers.add_parser("disrupt", help="Start disruption on target")
    p_disrupt.add_argument("ip", help="Target IP address")
    p_disrupt.add_argument("--methods", help="Comma-separated methods: drop,lag,throttle,duplicate,ood,corrupt,bandwidth,disconnect")
    p_disrupt.add_argument("--params", help="JSON params string")

    # stop
    p_stop = subparsers.add_parser("stop", help="Stop disruption")
    p_stop.add_argument("ip", nargs="?", help="Target IP address")
    p_stop.add_argument("--all", action="store_true", help="Stop all disruptions")

    # status
    subparsers.add_parser("status", help="Show engine status")

    # devices
    subparsers.add_parser("devices", help="List known devices")

    # plugins
    subparsers.add_parser("plugins", help="List plugins")

    # interactive
    subparsers.add_parser("interactive", aliases=["shell", "repl"], help="Interactive REPL mode")

    args = parser.parse_args()

    # Admin check
    if not _check_admin():
        print("[!] DupeZ requires administrator privileges.")
        print("    Run as Administrator or use: runas /user:Administrator dupez-cli")
        sys.exit(1)

    _print_banner()
    print("[*] Initializing engine (headless)...")

    from app.core.controller import AppController
    controller = AppController()

    log_startup()
    log_info("DupeZ CLI mode started")

    try:
        _CMD_MAP = {
            "scan": cmd_scan, "disrupt": cmd_disrupt, "stop": cmd_stop,
            "status": cmd_status, "devices": cmd_devices, "plugins": cmd_plugins,
            "interactive": cmd_interactive, "shell": cmd_interactive, "repl": cmd_interactive,
        }
        _CMD_MAP.get(args.command, cmd_interactive)(controller, args)
    finally:
        controller.shutdown()
        log_shutdown()

if __name__ == "__main__":
    main()

