# app/network/shared.py
"""
Shared OUI / vendor-lookup tables used by device_scan and enhanced_scanner.

The ``VENDOR_OUIS`` dict maps the first three octets of a MAC address
(lowercase, colon-separated) to a vendor name.  ``HOSTNAME_VENDORS``
maps known hostnames (lowercase) to a vendor override.
"""

from __future__ import annotations

from typing import Dict

__all__ = ["lookup_vendor"]

# Common MAC OUI prefixes -> vendor name
VENDOR_OUIS: Dict[str, str] = {
    # Sony / PlayStation
    "b4:0a:d8": "Sony Interactive Entertainment",
    "b4:0a:d9": "Sony Interactive Entertainment",
    "b4:0a:da": "Sony Interactive Entertainment",
    "b4:0a:db": "Sony Interactive Entertainment",
    "0c:fe:45": "Sony Interactive Entertainment",
    "f8:d0:ac": "Sony Interactive Entertainment",
    "00:04:1f": "Sony Computer Entertainment",
    "00:d9:d1": "Sony Interactive Entertainment",
    "28:3f:69": "Sony Interactive Entertainment",
    "fc:0f:e6": "Sony Interactive Entertainment",
    "a8:e3:ee": "Sony Interactive Entertainment",
    # Microsoft / Xbox
    "7c:ed:8d": "Microsoft Corporation",
    "98:de:d0": "Microsoft Corporation",
    "60:45:bd": "Microsoft Corporation",
    "00:50:f2": "Microsoft Corporation",
    "c8:3f:26": "Microsoft Corporation",
    "28:18:78": "Microsoft Corporation",
    # Nintendo
    "7c:bb:8a": "Nintendo Co., Ltd.",
    "34:af:2c": "Nintendo Co., Ltd.",
    "58:2f:40": "Nintendo Co., Ltd.",
    "d8:6b:f7": "Nintendo Co., Ltd.",
    "98:b6:e9": "Nintendo Co., Ltd.",
    "04:03:d6": "Nintendo Co., Ltd.",
    "e0:0c:7f": "Nintendo Co., Ltd.",
    "e8:4e:ce": "Nintendo Co., Ltd.",
    "40:f4:07": "Nintendo Co., Ltd.",
    # Apple
    "00:03:93": "Apple, Inc.",
    "00:05:02": "Apple, Inc.",
    "3c:15:c2": "Apple, Inc.",
    "a4:83:e7": "Apple, Inc.",
    "ac:de:48": "Apple, Inc.",
    "f0:18:98": "Apple, Inc.",
    "14:7d:da": "Apple, Inc.",
    "6c:4a:85": "Apple, Inc.",
    "78:7b:8a": "Apple, Inc.",
    "dc:a9:04": "Apple, Inc.",
    # Samsung
    "00:07:ab": "Samsung Electronics",
    "00:12:fb": "Samsung Electronics",
    "00:15:99": "Samsung Electronics",
    "00:16:32": "Samsung Electronics",
    "00:17:d5": "Samsung Electronics",
    "00:1a:8a": "Samsung Electronics",
    "00:21:19": "Samsung Electronics",
    "00:26:37": "Samsung Electronics",
    "14:49:e0": "Samsung Electronics",
    "84:25:db": "Samsung Electronics",
    # Google / Nest
    "f4:f5:d8": "Google, Inc.",
    "54:60:09": "Google, Inc.",
    "a4:77:33": "Google, Inc.",
    "20:df:b9": "Google, Inc.",
    # Amazon / Echo / Ring
    "fc:65:de": "Amazon Technologies Inc.",
    "68:37:e9": "Amazon Technologies Inc.",
    "40:b4:cd": "Amazon Technologies Inc.",
    "74:c2:46": "Amazon Technologies Inc.",
    "34:d2:70": "Amazon Technologies Inc.",
    # TP-Link
    "50:c7:bf": "TP-Link Technologies",
    "54:c8:0f": "TP-Link Technologies",
    "18:a6:f7": "TP-Link Technologies",
    "30:b5:c2": "TP-Link Technologies",
    # Netgear
    "00:09:5b": "NETGEAR",
    "00:0f:b5": "NETGEAR",
    "20:e5:2a": "NETGEAR",
    "b0:7f:b9": "NETGEAR",
    # Cisco / Linksys
    "00:00:0c": "Cisco Systems",
    "00:1b:0d": "Cisco Systems",
    "00:25:9c": "Cisco-Linksys",
    "58:6d:8f": "Cisco-Linksys",
    # Intel
    "00:02:b3": "Intel Corporate",
    "00:03:47": "Intel Corporate",
    "00:13:02": "Intel Corporate",
    "00:1b:21": "Intel Corporate",
    "3c:97:0e": "Intel Corporate",
    "68:05:ca": "Intel Corporate",
    # Raspberry Pi Foundation
    "b8:27:eb": "Raspberry Pi Foundation",
    "dc:a6:32": "Raspberry Pi Foundation",
    "e4:5f:01": "Raspberry Pi Foundation",
    # Dell
    "00:06:5b": "Dell Inc.",
    "00:08:74": "Dell Inc.",
    "14:18:77": "Dell Inc.",
    "18:a9:9b": "Dell Inc.",
    # HP
    "00:01:e6": "Hewlett Packard",
    "00:0d:9d": "Hewlett Packard",
    "10:1f:74": "Hewlett Packard",
    # ASUS
    "00:0c:6e": "ASUSTek Computer",
    "00:11:d8": "ASUSTek Computer",
    "1c:87:2c": "ASUSTek Computer",
    # Roku
    "dc:3a:5e": "Roku, Inc.",
    "b0:a7:37": "Roku, Inc.",
    "ac:3a:7a": "Roku, Inc.",
    # Sonos
    "00:0e:58": "Sonos, Inc.",
    "5c:aa:fd": "Sonos, Inc.",
    "78:28:ca": "Sonos, Inc.",
}

# Hostname patterns -> vendor override (lowercase keys)
HOSTNAME_VENDORS: Dict[str, str] = {
    "ps5":         "Sony Interactive Entertainment",
    "ps4":         "Sony Interactive Entertainment",
    "playstation": "Sony Interactive Entertainment",
    "xbox":        "Microsoft Corporation",
    "xboxone":     "Microsoft Corporation",
    "nintendo":    "Nintendo Co., Ltd.",
    "switch":      "Nintendo Co., Ltd.",
}


# Lazy-loaded scapy OUI DB (~35k entries). Imported on first miss in
# the curated table so we only pay the cost if needed. Falls back to
# "Unknown" if scapy isn't installed.
_SCAPY_MANUFDB = None
_SCAPY_MANUFDB_TRIED = False


def _scapy_manuf_lookup(mac_colon: str) -> str:
    """Consult scapy's full IEEE OUI database. Returns ''Unknown'' on miss."""
    global _SCAPY_MANUFDB, _SCAPY_MANUFDB_TRIED
    if not _SCAPY_MANUFDB_TRIED:
        _SCAPY_MANUFDB_TRIED = True
        try:
            from scapy.data import MANUFDB  # type: ignore
            _SCAPY_MANUFDB = MANUFDB
        except Exception:
            _SCAPY_MANUFDB = None
    if _SCAPY_MANUFDB is None:
        return "Unknown"
    try:
        result = _SCAPY_MANUFDB.lookup(mac_colon)
    except Exception:
        return "Unknown"
    # scapy returns (short, long) on hit, or (mac, mac) on miss
    if not result:
        return "Unknown"
    short, long_name = result if isinstance(result, tuple) else (None, result)
    if long_name and long_name.lower() != mac_colon.lower():
        return str(long_name)
    return "Unknown"


def lookup_vendor(mac: str) -> str:
    """Return the vendor string for *mac*, or ``'Unknown'``.

    Accepts any common MAC format: colon, hyphen, or dot-separated.
    Consults the curated ``VENDOR_OUIS`` table first (fast, gaming-focused),
    then falls back to scapy's full IEEE OUI database when installed.
    """
    if not mac or mac.lower() in ("unknown", ""):
        return "Unknown"

    # Normalise to lowercase colon-separated
    cleaned = mac.replace("-", ":").replace(".", "").lower()

    # Handle Cisco-style aabb.ccdd.eeff (12 hex chars, no colons)
    if ":" not in cleaned and len(cleaned) == 12:
        cleaned = ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))

    prefix = ":".join(cleaned.split(":")[:3])
    hit = VENDOR_OUIS.get(prefix)
    if hit:
        return hit
    return _scapy_manuf_lookup(cleaned)
