from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services import transcribe


@pytest.fixture(autouse=True)
def _reset_transcribe_cache():
    transcribe._reset_model()
    yield
    transcribe._reset_model()


def test_transcribe_options_default_to_sequential():
    options = transcribe.transcribe_options_from_mapping({})
    assert options["inference_mode"] == "sequential"
    assert options["batch_size"] == 16
    assert options["chunk_length"] is None


def test_transcribe_options_from_mapping_and_yaml_keys():
    options = transcribe.transcribe_options_from_mapping(
        {
            "inference_mode": "batched",
            "batch_size": 8,
            "chunk_length": 30,
        }
    )
    assert options["inference_mode"] == "batched"
    assert options["batch_size"] == 8
    assert options["chunk_length"] == 30


def test_transcribe_options_accepts_distil_large_v3():
    options = transcribe.transcribe_options_from_mapping(
        {"WHISPER_FASTER_MODEL": "distil-large-v3"}
    )
    assert options["model_id"] == "distil-large-v3"


def test_validate_whisper_model_id_rejects_unknown_short_name():
    with pytest.raises(ValueError, match="Unknown whisper model_id"):
        transcribe._validate_whisper_model_id("not-a-real-model")


def test_validate_whisper_model_id_allows_huggingface_repo_id():
    transcribe._validate_whisper_model_id("Systran/faster-distil-whisper-large-v3")


def test_resolve_inference_mode_rejects_unknown_value():
    with pytest.raises(ValueError, match="Invalid inference_mode"):
        transcribe._resolve_inference_mode("parallel")


def test_force_sequential_overrides_batched_mode(tmp_path: Path):
    wav_path = tmp_path / "audio.wav"
    wav_path.write_bytes(b"RIFF")

    mock_model = MagicMock()
    mock_model.transcribe.return_value = (
        [SimpleNamespace(start=0.0, end=1.0, text=" hello", words=None)],
        SimpleNamespace(language="pt", language_probability=0.99, duration=1.0),
    )

    with patch.object(transcribe, "_get_model", return_value=(mock_model, "int8")) as get_model:
        with patch.object(transcribe, "_get_batched_pipeline") as get_batched:
            result = transcribe.transcribe_wav(
                wav_path,
                inference_mode="batched",
                force_sequential=True,
            )

    get_model.assert_called_once()
    get_batched.assert_not_called()
    assert result["run"]["requested_inference_mode"] == "batched"
    assert result["run"]["inference_mode"] == "sequential"
    assert result["run"]["force_sequential"] is True


def test_batched_mode_uses_batched_pipeline(tmp_path: Path):
    wav_path = tmp_path / "audio.wav"
    wav_path.write_bytes(b"RIFF")

    mock_pipeline = MagicMock()
    mock_pipeline.transcribe.return_value = (
        [SimpleNamespace(start=0.0, end=1.0, text=" hello", words=None)],
        SimpleNamespace(language="pt", language_probability=0.99, duration=1.0),
    )

    with patch.object(
        transcribe,
        "_get_batched_pipeline",
        return_value=(mock_pipeline, "float16"),
    ) as get_batched:
        with patch.object(transcribe, "_get_model") as get_model:
            result = transcribe.transcribe_wav(
                wav_path,
                inference_mode="batched",
                batch_size=16,
                chunk_length=30,
            )

    get_batched.assert_called_once()
    get_model.assert_not_called()
    mock_pipeline.transcribe.assert_called_once()
    _, kwargs = mock_pipeline.transcribe.call_args
    assert kwargs["batch_size"] == 16
    assert kwargs["chunk_length"] == 30
    assert result["run"]["inference_mode"] == "batched"
    assert result["run"]["batch_size"] == 16
    assert result["run"]["chunk_length"] == 30
