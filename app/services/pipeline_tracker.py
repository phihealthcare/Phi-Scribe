from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.services.pipeline_steps import PIPELINE_STEPS, omitted_pipeline_steps_for_config, step_filename, step_meta

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "hf_token",
        "token",
        "secret",
        "password",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: ("<redacted>" if str(key).lower() in _SENSITIVE_KEYS else _sanitize(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _duration_fields(duration_ms: int | float | None) -> dict[str, float | None]:
    if duration_ms is None:
        return {
            "duration_ms": None,
            "duration_s": None,
        }
    rounded_ms = round(float(duration_ms), 2)
    return {
        "duration_ms": rounded_ms,
        "duration_s": round(rounded_ms / 1000.0, 4),
    }


def pipeline_log_dir(base_dir: Path, run_id: str) -> Path:
    return base_dir / f"{run_id}.pipeline"


LLM_REQUESTS_FILENAME = "llm_requests.json"


def tracker_from_config(
    config: Mapping[str, Any],
    *,
    run_id: str,
    log_dir: Path | None = None,
) -> PipelineTracker | None:
    enabled = bool(config.get("PIPELINE_DEBUG_LOG_ENABLED"))
    if not enabled:
        return None

    if log_dir is None:
        processed_folder = Path(str(config.get("PROCESSED_FOLDER", "uploads/processed")))
        log_dir = pipeline_log_dir(processed_folder, run_id)

    omitted_step_ids = omitted_pipeline_steps_for_config(config)
    return PipelineTracker(
        run_id=run_id,
        log_dir=log_dir,
        omitted_step_ids=omitted_step_ids,
    )


class PipelineTracker:
    def __init__(
        self,
        *,
        run_id: str,
        log_dir: Path,
        omitted_step_ids: frozenset[str] | None = None,
    ) -> None:
        self.run_id = run_id
        self.log_dir = log_dir.resolve()
        self._omitted_step_ids = frozenset(omitted_step_ids or ())
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._entries: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._remove_omitted_step_files()
        self._load_existing_manifest()

    def _is_omitted(self, step_id: str) -> bool:
        return step_id in self._omitted_step_ids

    def _remove_omitted_step_files(self) -> None:
        for step_id in self._omitted_step_ids:
            path = self.log_dir / step_filename(step_id)
            if path.is_file():
                path.unlink()

    def _load_existing_manifest(self) -> None:
        manifest_path = self.manifest_path()
        if not manifest_path.is_file():
            return
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        steps = manifest.get("steps")
        if isinstance(steps, list):
            self._entries = [
                item
                for item in steps
                if isinstance(item, dict) and not self._is_omitted(str(item.get("step_id", "")))
            ]

    def record(
        self,
        step_id: str,
        *,
        request: Any = None,
        response: Any = None,
        error: str | None = None,
        duration_ms: int | float | None = None,
        skipped: bool = False,
        skip_reason: str | None = None,
    ) -> Path:
        if self._is_omitted(step_id):
            return self.manifest_path()

        with self._lock:
            return self._record_unlocked(
                step_id,
                request=request,
                response=response,
                error=error,
                duration_ms=duration_ms,
                skipped=skipped,
                skip_reason=skip_reason,
            )

    def _record_unlocked(
        self,
        step_id: str,
        *,
        request: Any = None,
        response: Any = None,
        error: str | None = None,
        duration_ms: int | float | None = None,
        skipped: bool = False,
        skip_reason: str | None = None,
    ) -> Path:
        meta = step_meta(step_id)
        entry: dict[str, Any] = {
            **meta,
            "run_id": self.run_id,
            "timestamp": _utc_now(),
            "skipped": skipped,
            "skip_reason": skip_reason,
            **_duration_fields(duration_ms),
            "request": _sanitize(request),
            "response": _sanitize(response),
            "error": error,
        }

        path = self.log_dir / step_filename(step_id)
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")

        self._entries = [item for item in self._entries if item.get("step_id") != step_id]
        self._entries.append(
            {
                "step_id": step_id,
                "step_order": meta["order"],
                "label": meta["label"],
                "endpoint": meta["endpoint"],
                "file": str(path),
                "skipped": skipped,
                "error": error,
                **_duration_fields(duration_ms),
            }
        )
        self._write_manifest()
        return path

    def amend(self, step_id: str, **fields: Any) -> Path | None:
        if self._is_omitted(step_id):
            return None
        with self._lock:
            return self._amend_unlocked(step_id, **fields)

    def _amend_unlocked(self, step_id: str, **fields: Any) -> Path | None:
        path = self.log_dir / step_filename(step_id)
        if not path.is_file():
            return None
        entry = json.loads(path.read_text(encoding="utf-8"))
        for key, value in fields.items():
            if key in {"request", "response"} and isinstance(value, Mapping):
                current = entry.get(key) or {}
                if isinstance(current, dict):
                    current = dict(current)
                    current.update(_sanitize(value))
                    entry[key] = current
                else:
                    entry[key] = _sanitize(value)
            else:
                if key == "duration_ms":
                    entry.update(_duration_fields(value))
                else:
                    entry[key] = _sanitize(value)
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")

        for item in self._entries:
            if item.get("step_id") == step_id:
                if "error" in fields:
                    item["error"] = fields["error"]
                if "duration_ms" in fields:
                    item.update(_duration_fields(fields["duration_ms"]))
                break
        self._write_manifest()
        return path

    def skip(self, step_id: str, *, reason: str, request: Any = None) -> Path:
        return self.record(
            step_id,
            request=request,
            skipped=True,
            skip_reason=reason,
        )

    def llm_requests_path(self) -> Path:
        return self.log_dir / LLM_REQUESTS_FILENAME

    def append_llm_request(
        self,
        *,
        step_id: str | None = None,
        request: Any = None,
        response: Any = None,
        error: str | None = None,
        duration_ms: int | float | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> Path:
        """Append one LLM HTTP exchange to the accumulated llm_requests.json log."""
        with self._lock:
            return self._append_llm_request_unlocked(
                step_id=step_id,
                request=request,
                response=response,
                error=error,
                duration_ms=duration_ms,
                meta=meta,
            )

    def _append_llm_request_unlocked(
        self,
        *,
        step_id: str | None = None,
        request: Any = None,
        response: Any = None,
        error: str | None = None,
        duration_ms: int | float | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> Path:
        path = self.llm_requests_path()
        if path.is_file():
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                document = {"run_id": self.run_id, "requests": []}
        else:
            document = {"run_id": self.run_id, "requests": []}

        requests = document.get("requests")
        if not isinstance(requests, list):
            requests = []

        entry: dict[str, Any] = {
            "seq": len(requests) + 1,
            "timestamp": _utc_now(),
            "step_id": step_id,
            **_duration_fields(duration_ms),
            "request": _sanitize(request),
            "response": _sanitize(response),
            "error": error,
        }
        if meta:
            entry["meta"] = _sanitize(dict(meta))

        requests.append(entry)
        document["run_id"] = self.run_id
        document["updated_at"] = _utc_now()
        document["requests"] = requests
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        return path

    def manifest_path(self) -> Path:
        return self.log_dir / "manifest.json"

    def _write_manifest(self) -> None:
        manifest = {
            "run_id": self.run_id,
            "updated_at": _utc_now(),
            "log_dir": str(self.log_dir),
            "llm_requests_file": str(self.llm_requests_path()),
            "steps": sorted(self._entries, key=lambda item: item["step_order"]),
            "step_labels": {
                step_id: meta["label"]
                for step_id, meta in sorted(PIPELINE_STEPS.items(), key=lambda x: x[1]["order"])
                if not self._is_omitted(step_id)
            },
        }
        self.manifest_path().write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
