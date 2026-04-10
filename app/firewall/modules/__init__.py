"""
Disruption module package — individual packet manipulation modules.

Each module is a DisruptionModule subclass extracted from the original
monolithic native_divert_engine.py. The base class, WINDIVERT_ADDRESS,
and direction constants remain in native_divert_engine.py since they're
tightly coupled to the WinDivert ctypes layer.

All module classes and the MODULE_MAP registry are re-exported here for
convenient import.
"""

from app.firewall.modules.drop import DropModule
from app.firewall.modules.lag import LagModule
from app.firewall.modules.duplicate import DuplicateModule
from app.firewall.modules.throttle import ThrottleModule
from app.firewall.modules.corrupt import CorruptModule
from app.firewall.modules.bandwidth import BandwidthModule
from app.firewall.modules.ood import OODModule
from app.firewall.modules.rst import RSTModule
from app.firewall.modules.disconnect import DisconnectModule
from app.firewall.modules.godmode import GodModeModule
from app.firewall.modules.dupe_engine import DupeEngineModule

# Core module registry — maps method name strings to module classes.
# Phase 1/3/7 modules (statistical_models, tick_sync, stealth) register
# themselves separately via lazy import in native_divert_engine.py.
CORE_MODULE_MAP = {
    "drop":       DropModule,
    "lag":        LagModule,
    "duplicate":  DuplicateModule,
    "throttle":   ThrottleModule,
    "corrupt":    CorruptModule,
    "bandwidth":  BandwidthModule,
    "ood":        OODModule,
    "rst":        RSTModule,
    "disconnect": DisconnectModule,
    "godmode":    GodModeModule,
    "dupe":       DupeEngineModule,
}

__all__ = [
    "DropModule", "LagModule", "DuplicateModule", "ThrottleModule",
    "CorruptModule", "BandwidthModule", "OODModule", "RSTModule",
    "DisconnectModule", "GodModeModule", "DupeEngineModule",
    "CORE_MODULE_MAP",
]
