# app/firewall/__init__.py

from .blocker import block_ip, unblock_ip, is_blocking
from .win_divert import start_divert, stop_divert
