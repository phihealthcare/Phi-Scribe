"""Per-step wall-clock timing for POST /upload — debug slow preprocess pipelines."""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

UPLOAD_TIMING_FILENAME = "upload_timing.json"


class UploadStepTimer:
    """Collects wall-clock duration for each upload/preprocess sub-step."""

    def __init__(self, *, file_id: str) -> None:
        self.file_id = file_id
        self._steps: list[dict[str, Any]] = []
        self._started = time.perf_counter()

    @contextmanager
    def step(self, name: str, **meta: Any) -> Iterator[None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - t0) * 1000
            entry: dict[str, Any] = {
                "step": name,
                "duration_ms": round(duration_ms, 2),
                "duration_s": round(duration_ms / 1000, 4),
            }
            if meta:
                entry["meta"] = meta
            self._steps.append(entry)
            logger.info(
                "[upload-timing] file_id=%s step=%s duration_s=%.3f",
                self.file_id,
                name,
                duration_ms / 1000,
            )

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._started) * 1000

    def last_step_duration_ms(self) -> float | None:
        if not self._steps:
            return None
        return float(self._steps[-1]["duration_ms"])

    def sum_since(self, start_index: int) -> float | None:
        if start_index >= len(self._steps):
            return None
        return sum(float(step["duration_ms"]) for step in self._steps[start_index:])

    def step_count(self) -> int:
        return len(self._steps)

    def sum_tracked_ms(self) -> float:
        return sum(float(step["duration_ms"]) for step in self._steps)

    def to_dict(self) -> dict[str, Any]:
        tracked_ms = self.sum_tracked_ms()
        elapsed_ms = self.elapsed_ms()
        return {
            "file_id": self.file_id,
            "steps": list(self._steps),
            "total_tracked_ms": round(tracked_ms, 2),
            "total_tracked_s": round(tracked_ms / 1000, 4),
            "total_elapsed_ms": round(elapsed_ms, 2),
            "total_elapsed_s": round(elapsed_ms / 1000, 4),
            "untracked_ms": round(max(0.0, elapsed_ms - tracked_ms), 2),
        }

    def write_json(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def log_summary(self) -> None:
        body = self.to_dict()
        parts = " | ".join(f"{item['step']}={item['duration_s']:.2f}s" for item in body["steps"])
        logger.info(
            "[upload-timing] file_id=%s TOTAL elapsed=%.2fs tracked=%.2fs — %s",
            self.file_id,
            body["total_elapsed_s"],
            body["total_tracked_s"],
            parts or "(no steps)",
        )


def upload_timing_path(base_dir: Path, file_id: str) -> Path:
    """Standalone timing file when pipeline debug logging is disabled."""
    return base_dir / f"{file_id}.{UPLOAD_TIMING_FILENAME}"


def pipeline_upload_timing_path(log_dir: Path) -> Path:
    return log_dir / UPLOAD_TIMING_FILENAME
