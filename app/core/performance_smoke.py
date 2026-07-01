"""Local performance smoke checks for safe supportability surfaces."""

from __future__ import annotations

import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List

SCHEMA = "dupez.performance-smoke.v1"


@dataclass(frozen=True)
class PerfResult:
    name: str
    budget_ms: float
    samples_ms: List[float]

    @property
    def p50_ms(self) -> float:
        return statistics.median(self.samples_ms) if self.samples_ms else 0.0

    @property
    def p95_ms(self) -> float:
        if not self.samples_ms:
            return 0.0
        samples = sorted(self.samples_ms)
        index = min(len(samples) - 1, int(round(0.95 * (len(samples) - 1))))
        return samples[index]

    @property
    def max_ms(self) -> float:
        return max(self.samples_ms) if self.samples_ms else 0.0

    @property
    def ok(self) -> bool:
        return self.p95_ms <= self.budget_ms

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "budget_ms": self.budget_ms,
            "p50_ms": round(self.p50_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "samples_ms": [round(value, 3) for value in self.samples_ms],
            "ok": self.ok,
        }


def _measure(name: str, budget_ms: float, iterations: int, fn: Callable[[], Any]) -> PerfResult:
    samples: List[float] = []
    for _ in range(max(iterations, 1)):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    return PerfResult(name=name, budget_ms=budget_ms, samples_ms=samples)


def _bench_storage_status() -> None:
    from app.core.storage_status import build_storage_status

    build_storage_status()


def _bench_retention_empty() -> None:
    from app.core.privacy import build_retention_plan

    with tempfile.TemporaryDirectory(prefix="dupez-perf-") as tmp:
        root = Path(tmp)
        build_retention_plan(
            data_dir=root / "data",
            capture_dir=root / "captures",
            log_dir=root / "logs",
            crash_dir=root / "crashes",
            report_dir=root / "reports",
            backup_dir=root / "backups",
        )


def _bench_scenario_report() -> None:
    from app.core.scenario_report import build_scenario_report

    build_scenario_report([
        {
            "target": "192.168.1.x",
            "methods": ["lag"],
            "params_fingerprint": "sha256:unit",
            "started_at_unix": 1_756_000_000,
            "elapsed_seconds": 1.25,
            "automatic_stop_armed": True,
        }
    ])


def _bench_support_bundle() -> None:
    from app.core.support_bundle import build_support_bundle

    build_support_bundle()


def run_performance_smoke(
    *,
    iterations: int = 5,
    include_support_bundle: bool = False,
) -> Dict[str, Any]:
    """Run bounded local performance checks without starting packet capture."""
    checks = [
        _measure("storage_status", 100.0, iterations, _bench_storage_status),
        _measure("retention_empty_roots", 50.0, iterations, _bench_retention_empty),
        _measure("scenario_report", 25.0, iterations, _bench_scenario_report),
    ]
    if include_support_bundle:
        checks.append(
            _measure("support_bundle", 3000.0, iterations, _bench_support_bundle)
        )

    payload = {
        "schema": SCHEMA,
        "iterations": max(iterations, 1),
        "include_support_bundle": include_support_bundle,
        "checks": [check.as_dict() for check in checks],
    }
    payload["ok"] = all(check["ok"] for check in payload["checks"])
    return payload
