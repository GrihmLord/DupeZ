from __future__ import annotations

import json

from app.core.defender_posture import parse_defender_json


def test_parse_defender_json_passes_clean_posture() -> None:
    posture = parse_defender_json(
        json.dumps(
            {
                "antivirusEnabled": True,
                "realTimeProtectionEnabled": True,
                "amServiceEnabled": True,
                "recentDetectionCount": 0,
            }
        )
    )

    assert posture.available is True
    assert posture.status == "pass"
    assert posture.has_recent_detection is False


def test_parse_defender_json_warns_on_recent_detection_without_paths() -> None:
    posture = parse_defender_json(
        json.dumps(
            {
                "antivirusEnabled": True,
                "realTimeProtectionEnabled": True,
                "amServiceEnabled": True,
                "recentDetectionCount": 2,
                "latestThreatName": "PUA:Win32/FalsePositive",
                "latestActionSuccess": True,
                "latestDetectionTime": "2026-07-01T12:00:00.0000000-05:00",
                "resources": ["C:/Users/Owner/AppData/Local/Temp/private.exe"],
            }
        )
    )

    assert posture.status == "warn"
    assert posture.recent_detection_count == 2
    assert posture.latest_threat_name == "PUA:Win32/FalsePositive"
    assert "Users/Owner" not in posture.message


def test_parse_defender_json_handles_unavailable_payload() -> None:
    posture = parse_defender_json("not-json")

    assert posture.available is False
    assert posture.status == "unavailable"
