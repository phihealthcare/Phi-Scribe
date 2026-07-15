import json
from pathlib import Path

import pytest

from app.services.pipeline_steps import (
    TRANSCRIBE_01_DIARIZATION,
    TRANSCRIBE_02_WHISPER,
    TRANSCRIBE_03_FORMAT_SPEAKERS,
    TRANSCRIBE_04B_LLM_DIARIZATION_LABELS,
    TRANSCRIBE_05A_LLM_SOAP_SUBJETIVO,
    TRANSCRIBE_05_LLM_SOAP,
    omitted_pipeline_steps_for_config,
    soap_enabled_for_config,
    step_filename,
    soap_split_enabled_for_config,
)
from app.services.pipeline_tracker import PipelineTracker


def test_omitted_steps_when_diarization_and_split_disabled():
    config = {
        "DIARIZATION_ENABLED": False,
        "SOAP_SPLIT_ENABLED": False,
    }
    omitted = omitted_pipeline_steps_for_config(config)
    assert TRANSCRIBE_01_DIARIZATION in omitted
    assert TRANSCRIBE_03_FORMAT_SPEAKERS in omitted
    assert TRANSCRIBE_04B_LLM_DIARIZATION_LABELS in omitted
    assert TRANSCRIBE_05A_LLM_SOAP_SUBJETIVO in omitted
    assert TRANSCRIBE_05_LLM_SOAP not in omitted


def test_omitted_steps_when_split_enabled():
    config = {
        "DIARIZATION_ENABLED": True,
        "SOAP_SPLIT_ENABLED": True,
    }
    omitted = omitted_pipeline_steps_for_config(config)
    assert TRANSCRIBE_05_LLM_SOAP in omitted
    assert TRANSCRIBE_05A_LLM_SOAP_SUBJETIVO not in omitted


def test_omitted_steps_when_soap_disabled():
    config = {
        "DIARIZATION_ENABLED": True,
        "SOAP_ENABLED": False,
        "SOAP_SPLIT_ENABLED": False,
    }
    omitted = omitted_pipeline_steps_for_config(config)
    assert TRANSCRIBE_05_LLM_SOAP in omitted
    assert TRANSCRIBE_05A_LLM_SOAP_SUBJETIVO in omitted


def test_tracker_skip_does_not_create_file_for_omitted_step(tmp_path: Path):
    omitted = omitted_pipeline_steps_for_config(
        {"DIARIZATION_ENABLED": False, "SOAP_SPLIT_ENABLED": False}
    )
    tracker = PipelineTracker(
        run_id="test-run",
        log_dir=tmp_path,
        omitted_step_ids=omitted,
    )

    tracker.skip(TRANSCRIBE_01_DIARIZATION, reason="diarization_disabled")
    tracker.skip(TRANSCRIBE_03_FORMAT_SPEAKERS, reason="diarization_disabled")
    tracker.skip(TRANSCRIBE_04B_LLM_DIARIZATION_LABELS, reason="diarization_disabled")
    tracker.skip(TRANSCRIBE_05A_LLM_SOAP_SUBJETIVO, reason="soap_monolithic")
    tracker.record(
        TRANSCRIBE_02_WHISPER,
        request={"model": "large-v3"},
        response={"text": "ola"},
    )

    assert not (tmp_path / step_filename(TRANSCRIBE_01_DIARIZATION)).is_file()
    assert not (tmp_path / step_filename(TRANSCRIBE_03_FORMAT_SPEAKERS)).is_file()
    assert not (tmp_path / step_filename(TRANSCRIBE_04B_LLM_DIARIZATION_LABELS)).is_file()
    assert not (tmp_path / step_filename(TRANSCRIBE_05A_LLM_SOAP_SUBJETIVO)).is_file()
    assert (tmp_path / step_filename(TRANSCRIBE_02_WHISPER)).is_file()

    manifest = json.loads(tracker.manifest_path().read_text(encoding="utf-8"))
    step_ids = {item["step_id"] for item in manifest["steps"]}
    assert step_ids == {TRANSCRIBE_02_WHISPER}
    assert TRANSCRIBE_01_DIARIZATION not in manifest["step_labels"]


def test_tracker_removes_stale_omitted_files_on_init(tmp_path: Path):
    stale = tmp_path / step_filename(TRANSCRIBE_01_DIARIZATION)
    stale.write_text("{}", encoding="utf-8")

    omitted = omitted_pipeline_steps_for_config(
        {"DIARIZATION_ENABLED": False, "SOAP_SPLIT_ENABLED": False}
    )
    PipelineTracker(run_id="test-run", log_dir=tmp_path, omitted_step_ids=omitted)

    assert not stale.is_file()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (False, False),
        ("false", False),
        ("true", True),
        (True, True),
    ],
)
def test_soap_enabled_for_config(raw, expected):
    assert soap_enabled_for_config({"SOAP_ENABLED": raw}) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (False, False),
        ("false", False),
        ("true", True),
        (True, True),
    ],
)
def test_soap_split_enabled_for_config(raw, expected):
    assert soap_split_enabled_for_config({"SOAP_SPLIT_ENABLED": raw}) is expected


def test_monolithic_soap_loads_single_prompt_file(tmp_path: Path):
    prompt_path = tmp_path / "soap-draft.md"
    prompt_path.write_text("Prompt monolítico único.", encoding="utf-8")

    from app.services.soap_draft import load_soap_prompt

    assert load_soap_prompt(prompt_path=prompt_path) == "Prompt monolítico único."


def test_append_llm_request_accumulates_in_single_file(tmp_path: Path):
    tracker = PipelineTracker(run_id="test-run", log_dir=tmp_path)

    tracker.append_llm_request(
        step_id="transcribe_04_llm_asr_fix",
        request={
            "url": "https://api.example.com/api/medgemma",
            "model": "gemma3:12b-it-qat",
            "prompt": "primeira",
            "system_prompt": "system-a",
        },
        response={"text": "resposta-a"},
        duration_ms=100.5,
        meta={"attempt": 1},
    )
    tracker.append_llm_request(
        step_id="transcribe_05a_llm_soap_subjetivo",
        request={
            "url": "https://api.example.com/api/medgemma",
            "model": "gemma3:12b-it-qat",
            "prompt": "segunda",
            "system_prompt": "system-b",
        },
        response={"text": "resposta-b"},
        duration_ms=200.25,
        meta={"attempt": 2, "soap_section": "subjetivo"},
    )

    log_path = tracker.llm_requests_path()
    assert log_path.is_file()
    document = json.loads(log_path.read_text(encoding="utf-8"))
    assert document["run_id"] == "test-run"
    assert len(document["requests"]) == 2
    assert document["requests"][0]["seq"] == 1
    assert document["requests"][0]["request"]["prompt"] == "primeira"
    assert document["requests"][0]["duration_ms"] == 100.5
    assert document["requests"][0]["duration_s"] == 0.1005
    assert document["requests"][1]["seq"] == 2
    assert document["requests"][1]["duration_ms"] == 200.25
    assert document["requests"][1]["duration_s"] == 0.2003
    assert document["requests"][1]["meta"]["soap_section"] == "subjetivo"

    manifest = json.loads(tracker.manifest_path().read_text(encoding="utf-8"))
    assert manifest["llm_requests_file"] == str(log_path)
