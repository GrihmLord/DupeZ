"""Episode recorder — captures labeled dupe attempts for offline ML training.

Writes one JSONL file per engine session to ``app/data/episodes/`` with
per-window feature vectors plus lifecycle events (``cut_start``,
``cut_end``, ``engine_stop``, custom ``outcome`` labels from the UI).

The recorder runs on a background thread with a bounded queue — the
packet hot path never blocks on disk I/O. If the queue saturates
(operator runs without a fast disk, etc.), new samples are dropped and
the drop count is logged so the data doesn't silently skew.

This is the data substrate for:
    * 1D CNN flush detector          (window vectors leading up to cut_end)
    * LightGBM RPC burst classifier  (control-plane spikes vs baseline)
    * QRF cut-duration regressor     (cut_start → cut_end deltas)
    * VAE stealth keepalive          (baseline windows only)
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.logs.logger import log_error, log_info, log_warning

__all__ = ["EpisodeRecorder", "DEFAULT_EPISODE_DIR", "rotate_episodes"]

DEFAULT_EPISODE_DIR: Path = Path("app/data/episodes")
_MAX_QUEUE: int = 4096
_FLUSH_INTERVAL_S: float = 2.0

# v5.7.1 retention defaults. Operators with very long-running installs
# accumulate hundreds of MBs over months — the on-disk store and the
# learning-loop cold-read scan both grow linearly with file count.
# These are intentionally generous (90 days / 5000 files) so power
# users keep their training data, but bounded.
_DEFAULT_RETENTION_DAYS: int = 90
_DEFAULT_MAX_FILES: int = 5000


def rotate_episodes(
    episode_dir: Optional[Path] = None,
    *,
    retention_days: int = _DEFAULT_RETENTION_DAYS,
    max_files: int = _DEFAULT_MAX_FILES,
) -> int:
    """Delete episode files older than *retention_days* OR beyond *max_files*.

    Two-pass policy:

    1. **Age cap.** Anything with ``mtime`` older than the retention
       cutoff is removed regardless of count.
    2. **Count cap.** If more than *max_files* remain, oldest-first
       trim until at most *max_files* survive.

    Operates atomically per-file (unlink each in isolation); failures
    on individual files are logged but don't halt the pass. Safe to
    call from a background thread; never raises.

    Args:
        episode_dir: directory to clean. Defaults to
            ``DEFAULT_EPISODE_DIR``.
        retention_days: episodes older than this are deleted. Default 90.
        max_files: hard ceiling on retained files. Default 5000.

    Returns:
        Number of files actually removed.
    """
    target = Path(episode_dir) if episode_dir else DEFAULT_EPISODE_DIR
    if not target.exists():
        return 0

    cutoff_ts = time.time() - (max(0, retention_days) * 86400.0)
    removed = 0

    try:
        files = list(target.glob("episode_*.jsonl"))
    except OSError as exc:
        log_warning(f"rotate_episodes: scan failed: {exc}")
        return 0

    # Pre-collect (path, mtime) so we sort once and reuse for both passes.
    entries = []
    for p in files:
        try:
            entries.append((p, p.stat().st_mtime))
        except OSError:
            continue

    # Pass 1: age cap.
    surviving = []
    for path, mtime in entries:
        if retention_days > 0 and mtime < cutoff_ts:
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                log_warning(
                    f"rotate_episodes: cannot delete {path.name}: {exc}"
                )
                surviving.append((path, mtime))
        else:
            surviving.append((path, mtime))

    # Pass 2: count cap on survivors. Oldest first so we keep the
    # most recent training data the learning loop relies on.
    if max_files > 0 and len(surviving) > max_files:
        surviving.sort(key=lambda t: t[1])  # oldest first
        overflow = surviving[: len(surviving) - max_files]
        for path, _mtime in overflow:
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                log_warning(
                    f"rotate_episodes: cannot delete {path.name}: {exc}"
                )

    if removed:
        log_info(
            f"rotate_episodes: removed {removed} stale episode file(s) "
            f"(retention={retention_days}d, max={max_files})"
        )
    return removed


class EpisodeRecorder:
    """Async JSONL writer for feature-vector episodes.

    Thread-safe: :meth:`record_window` and :meth:`record_event` can be
    called from the engine packet loop; all disk I/O happens on the
    recorder's own thread.
    """

    def __init__(
        self,
        out_dir: Optional[Path] = None,
        session_tag: str = "",
    ) -> None:
        self._out_dir: Path = Path(out_dir) if out_dir else DEFAULT_EPISODE_DIR
        self._out_dir.mkdir(parents=True, exist_ok=True)

        tag = session_tag or time.strftime("%Y%m%d_%H%M%S")
        self._path: Path = self._out_dir / f"episode_{tag}.jsonl"

        self._q: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue(_MAX_QUEUE)
        self._stop = threading.Event()
        self._dropped: int = 0
        self._written: int = 0

        self._thread = threading.Thread(
            target=self._worker, name="EpisodeRecorder", daemon=True
        )
        self._thread.start()
        log_info(f"[EPISODE] Recording → {self._path}")

    # ── public API ───────────────────────────────────────────────────
    def record_window(self, vec: List[float], ts: Optional[float] = None) -> None:
        """Queue a feature-vector sample."""
        self._enqueue({
            "kind": "window",
            "ts": ts if ts is not None else time.time(),
            "vec": vec,
        })

    def record_event(self, name: str, **payload: Any) -> None:
        """Queue a lifecycle or outcome event."""
        self._enqueue({
            "kind": "event",
            "ts": time.time(),
            "name": name,
            "payload": payload,
        })

    def stop(self, timeout: float = 3.0) -> None:
        """Flush and shut down the writer."""
        if self._stop.is_set():
            return
        self._stop.set()
        try:
            self._q.put_nowait(None)  # sentinel wakes the worker
        except queue.Full:
            pass
        self._thread.join(timeout=timeout)
        log_info(
            f"[EPISODE] Stopped — wrote {self._written}, "
            f"dropped {self._dropped} → {self._path}"
        )

    @property
    def path(self) -> Path:
        return self._path

    # ── internals ────────────────────────────────────────────────────
    def _enqueue(self, item: Dict[str, Any]) -> None:
        try:
            self._q.put_nowait(item)
        except queue.Full:
            self._dropped += 1
            if self._dropped % 1000 == 1:
                log_warning(f"[EPISODE] Queue full — dropped {self._dropped} samples")

    def _worker(self) -> None:
        try:
            with open(self._path, "a", buffering=1, encoding="utf-8") as fp:
                last_flush = time.monotonic()
                while not self._stop.is_set() or not self._q.empty():
                    try:
                        item = self._q.get(timeout=_FLUSH_INTERVAL_S)
                    except queue.Empty:
                        continue
                    if item is None:
                        break
                    try:
                        fp.write(json.dumps(item, separators=(",", ":")))
                        fp.write("\n")
                        self._written += 1
                    except (TypeError, ValueError) as exc:
                        log_warning(f"[EPISODE] Serialize failed: {exc}")
                    now = time.monotonic()
                    if now - last_flush >= _FLUSH_INTERVAL_S:
                        try:
                            fp.flush()
                            os.fsync(fp.fileno())
                        except OSError:
                            pass
                        last_flush = now
        except OSError as exc:
            log_error(f"[EPISODE] Writer failed: {exc}")
