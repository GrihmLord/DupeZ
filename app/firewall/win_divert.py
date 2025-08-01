# app/firewall/win_divert.py

import threading
import subprocess

_divert_process = None

def start_divert(ip: str):
    global _divert_process
    if _divert_process:
        stop_divert()

    command = [
        "WinDivert64.exe",  # Make sure this is in your working directory or PATH
        f"outbound and ip.DstAddr == {ip}", "--drop"
    ]
    _divert_process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def stop_divert():
    global _divert_process
    if _divert_process:
        _divert_process.terminate()
        _divert_process = None
