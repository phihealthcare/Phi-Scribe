import time
from unittest.mock import patch

from app.services.transcript_postprocess import (
    _split_transcript_for_asr_fix,
    edit_transcript,
    resolve_asr_fix_chunk_settings,
)


def test_resolve_asr_fix_chunk_settings_parallel_defaults() -> None:
    settings = resolve_asr_fix_chunk_settings()
    assert settings["chunk_max_words"] == 450
    assert settings["chunk_parallel"] is True
    assert settings["chunk_max_workers"] == 2


def test_resolve_asr_fix_chunk_settings_parallel_from_config() -> None:
    settings = resolve_asr_fix_chunk_settings(
        {
            "ASR_FIX_CHUNK_PARALLEL": "false",
            "ASR_FIX_CHUNK_MAX_WORKERS": "2",
        }
    )
    assert settings["chunk_parallel"] is False
    assert settings["chunk_max_workers"] == 2


def test_edit_transcript_chunked_parallel_preserves_order() -> None:
    text = " ".join(f"word{i}" for i in range(1000))
    chunks = _split_transcript_for_asr_fix(text, max_words=250)
    assert len(chunks) >= 4

    def fake_generate(**kwargs):
        meta = kwargs.get("tracker_request_meta") or {}
        index = int(meta["chunk_index"])
        chunk = chunks[index - 1]
        words = chunk.split()
        words[0] = f"marker{index}"
        return " ".join(words), f"raw{index}"

    with patch(
        "app.services.transcript_postprocess.medgemma_generate",
        side_effect=fake_generate,
    ):
        result = edit_transcript(
            text,
            enabled=True,
            provider="phihc",
            model="test",
            base_url="https://api.example.com",
            api_key="key",
            timeout=30,
            chunk_max_words=250,
            chunk_parallel=True,
            chunk_max_workers=4,
        )

    assert result.get("error") is None
    assert result["chunking"]["parallel"] is True
    assert result["chunking"]["chunk_count"] == len(chunks)
    merged = result["text"]
    for index in range(1, len(chunks) + 1):
        assert f"marker{index}" in merged
    assert merged.index("marker1") < merged.index("marker2")


def test_edit_transcript_chunked_parallel_is_faster_than_sequential() -> None:
    text = " ".join(f"word{i}" for i in range(1000))
    chunks = _split_transcript_for_asr_fix(text, max_words=250)

    def slow_generate(**kwargs):
        time.sleep(0.05)
        meta = kwargs.get("tracker_request_meta") or {}
        index = int(meta["chunk_index"])
        return chunks[index - 1], "raw"

    with patch(
        "app.services.transcript_postprocess.medgemma_generate",
        side_effect=slow_generate,
    ):
        parallel_started = time.perf_counter()
        parallel_result = edit_transcript(
            text,
            enabled=True,
            provider="phihc",
            model="test",
            base_url="https://api.example.com",
            api_key="key",
            timeout=30,
            chunk_max_words=250,
            chunk_parallel=True,
            chunk_max_workers=4,
        )
        parallel_elapsed = time.perf_counter() - parallel_started

    with patch(
        "app.services.transcript_postprocess.medgemma_generate",
        side_effect=slow_generate,
    ):
        sequential_started = time.perf_counter()
        sequential_result = edit_transcript(
            text,
            enabled=True,
            provider="phihc",
            model="test",
            base_url="https://api.example.com",
            api_key="key",
            timeout=30,
            chunk_max_words=250,
            chunk_parallel=False,
            chunk_max_workers=4,
        )
        sequential_elapsed = time.perf_counter() - sequential_started

    assert parallel_result["chunking"]["parallel"] is True
    assert sequential_result["chunking"]["parallel"] is False
    assert parallel_elapsed < sequential_elapsed * 0.75
