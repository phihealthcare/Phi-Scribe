import json
from pathlib import Path

from app.services.upload_timing import UploadStepTimer, pipeline_upload_timing_path, upload_timing_path


def test_upload_step_timer_records_durations(tmp_path: Path) -> None:
    timer = UploadStepTimer(file_id="abc-123")

    with timer.step("save_file", size_bytes=1024):
        pass
    with timer.step("normalize"):
        pass

    payload = timer.to_dict()
    assert payload["file_id"] == "abc-123"
    assert len(payload["steps"]) == 2
    assert payload["steps"][0]["step"] == "save_file"
    assert payload["steps"][0]["meta"] == {"size_bytes": 1024}
    assert payload["total_tracked_ms"] >= 0
    assert payload["total_elapsed_ms"] >= payload["total_tracked_ms"]

    out = timer.write_json(tmp_path / "upload_timing.json")
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["steps"][1]["step"] == "normalize"


def test_upload_timing_paths() -> None:
    assert upload_timing_path(Path("uploads/processed"), "id-1") == Path(
        "uploads/processed/id-1.upload_timing.json"
    )
    assert pipeline_upload_timing_path(Path("uploads/processed/id-1.pipeline")) == Path(
        "uploads/processed/id-1.pipeline/upload_timing.json"
    )


def test_sum_since_and_last_step() -> None:
    timer = UploadStepTimer(file_id="x")
    with timer.step("a"):
        pass
    with timer.step("b"):
        pass

    assert timer.last_step_duration_ms() is not None
    assert timer.sum_since(1) == timer.last_step_duration_ms()
    assert timer.sum_since(99) is None
