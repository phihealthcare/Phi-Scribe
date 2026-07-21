from __future__ import annotations

from unittest.mock import patch

import numpy as np

from app.services.diarization_realtime import SAMPLE_RATE, RealtimeDiarizationSession


def _silence_pcm16(seconds: float) -> bytes:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.int16).tobytes()


def _payload(turns: list[dict]) -> dict:
    return {"chunks": [{"turns": turns, "model": "nvidia/diar_sortformer_4spk-v1"}]}


def _session(**overrides) -> RealtimeDiarizationSession:
    kwargs = dict(window_s=2.0, overlap_s=1.0, use_daemon=True)
    kwargs.update(overrides)
    return RealtimeDiarizationSession(**kwargs)


def test_maybe_diarize_returns_none_before_window_s_accumulated() -> None:
    session = _session()
    session.push_audio(_silence_pcm16(1.0))  # < window_s (2.0)
    with patch("app.services.diarization_realtime._diarize_batch") as mock_diarize:
        assert session.maybe_diarize() is None
    mock_diarize.assert_not_called()


def test_first_tick_assigns_global_ids_by_sorted_appearance_and_commits_before_overlap() -> None:
    session = _session()
    session.push_audio(_silence_pcm16(2.0))  # exactly window_s, first tick needs no overlap yet

    raw_turns = [
        {"speaker": "speaker_1", "start_ms": 0, "end_ms": 1000},
        {"speaker": "speaker_2", "start_ms": 1000, "end_ms": 2000},
    ]
    with patch(
        "app.services.diarization_realtime._diarize_batch", return_value=_payload(raw_turns)
    ):
        committed = session.maybe_diarize()

    # commit_before_ms = buffer_end_ms(2000) - overlap_s*1000(1000) = 1000.
    # Only the turn ending at exactly 1000ms qualifies.
    assert committed == [{"speaker": "speaker_G0", "start_ms": 0, "end_ms": 1000}]
    assert session._global_turns == committed
    # The last overlap_s (1s) of raw audio is retained for the next tick.
    assert round(session._buffer_duration_s(), 2) == 1.0
    assert session._buffer_start_ms == 1000


def test_second_tick_matches_continuing_speaker_and_assigns_new_id_for_new_speaker() -> None:
    session = _session()
    session.push_audio(_silence_pcm16(2.0))
    first_raw_turns = [
        {"speaker": "speaker_1", "start_ms": 0, "end_ms": 1000},
        {"speaker": "speaker_2", "start_ms": 1000, "end_ms": 2000},
    ]
    with patch(
        "app.services.diarization_realtime._diarize_batch", return_value=_payload(first_raw_turns)
    ):
        session.maybe_diarize()
    # Buffer now holds the retained 1s tail (was speaker_2's turn, [1000,2000] absolute
    # -> rebased to window-local [0,1000] once diarized again in the next tick).

    session.push_audio(_silence_pcm16(2.0))  # need window_s + overlap_s = 3.0s total; have 1.0 + 2.0
    second_raw_turns = [
        # Local window is [0, 3000)ms, corresponding to absolute [1000, 4000)ms.
        {"speaker": "speaker_A", "start_ms": 0, "end_ms": 1000},  # same voice as speaker_2 (the retained tail)
        {"speaker": "speaker_B", "start_ms": 1000, "end_ms": 3000},  # a genuinely new speaker
    ]
    with patch(
        "app.services.diarization_realtime._diarize_batch", return_value=_payload(second_raw_turns)
    ):
        committed = session.maybe_diarize()

    # speaker_A fully overlaps speaker_G1 (speaker_2's global id) inside the shared
    # overlap window [1000, 2000)ms absolute -> matched, keeps speaker_G1, fully
    # committed (ends at 2000, the new commit_before_ms boundary).
    # speaker_B has no overlap with any previously-known speaker -> gets a new id
    # (speaker_G2), and is CLIPPED (not dropped) at the commit boundary (3000) since
    # part of its turn [2000,4000) straddles it — the [3000,4000) remainder is still
    # in the retained buffer tail and will be picked up on a later tick.
    assert committed == [
        {"speaker": "speaker_G1", "start_ms": 1000, "end_ms": 2000},
        {"speaker": "speaker_G2", "start_ms": 2000, "end_ms": 3000},
    ]
    assert session._next_global_id == [3]  # speaker_G0, speaker_G1 used; speaker_B -> speaker_G2 assigned


def test_speaker_absent_longer_than_overlap_gets_a_new_global_id() -> None:
    """Documents the known limitation: _match_local_to_global has no voice
    embedding fallback, so a speaker silent for longer than overlap_s cannot
    be re-identified and is assigned a brand new global id instead of being
    recognized as the same person."""
    session = _session()
    session.push_audio(_silence_pcm16(2.0))
    with patch(
        "app.services.diarization_realtime._diarize_batch",
        return_value=_payload([{"speaker": "speaker_1", "start_ms": 0, "end_ms": 2000}]),
    ):
        session.maybe_diarize()

    session.push_audio(_silence_pcm16(2.0))
    # The retained overlap window has NO turns at all (speaker was silent/gone),
    # so nothing can match against speaker_G0 in the shared overlap span.
    with patch(
        "app.services.diarization_realtime._diarize_batch",
        return_value=_payload([{"speaker": "speaker_1", "start_ms": 1000, "end_ms": 3000}]),
    ):
        committed = session.maybe_diarize()

    assert committed is not None
    assert committed[0]["speaker"] == "speaker_G1"  # NOT re-recognized as speaker_G0


def test_finalize_merges_remaining_buffer_and_returns_expected_shape() -> None:
    session = _session()
    session.push_audio(_silence_pcm16(1.5))  # below window_s — only flushed by finalize()

    with patch(
        "app.services.diarization_realtime._diarize_batch",
        return_value=_payload([{"speaker": "speaker_1", "start_ms": 0, "end_ms": 1500}]),
    ):
        result = session.finalize()

    assert result["speakers"] == ["speaker_G0"]
    assert result["turns"] == [{"speaker": "speaker_G0", "start_ms": 0, "end_ms": 1500}]
    assert result["turn_count"] == 1
    assert session._buffer_duration_s() == 0.0


def test_finalize_with_no_pending_audio_returns_prior_committed_turns() -> None:
    session = _session()
    result = session.finalize()
    assert result["turns"] == []
    assert result["speakers"] == []
    assert result["turn_count"] == 0


def test_continuous_speaker_across_many_ticks_has_no_gaps_or_overlaps_in_final_coverage() -> None:
    """Regression test for a real bug caught during development: turns
    straddling a tick's commit boundary were being dropped entirely instead
    of clipped, silently losing coverage for whichever portion preceded the
    boundary. A single speaker talking continuously across several ticks
    must end up fully covered start-to-end in the final merged turns, with
    no gaps and no double-counted overlaps."""
    session = _session(window_s=2.0, overlap_s=1.0)

    def fake_diarize_batch(wav_paths, **kwargs):
        # Whole current buffer is one continuous "speaker_1" turn, local to this window.
        duration_ms = int(session._buffer_duration_s() * 1000)
        return _payload([{"speaker": "speaker_1", "start_ms": 0, "end_ms": duration_ms}])

    with patch(
        "app.services.diarization_realtime._diarize_batch", side_effect=fake_diarize_batch
    ):
        session.push_audio(_silence_pcm16(2.0))
        session.maybe_diarize()
        for _ in range(4):
            session.push_audio(_silence_pcm16(2.0))
            session.maybe_diarize()
        session.push_audio(_silence_pcm16(0.7))  # partial tail, only flushed by finalize()
        result = session.finalize()

    assert result["speakers"] == ["speaker_G0"]  # never fragmented into multiple ids
    turns = result["turns"]
    total_pushed_ms = int((2.0 + 4 * 2.0 + 0.7) * 1000)
    assert turns[0]["start_ms"] == 0
    assert turns[-1]["end_ms"] == total_pushed_ms
    # merge_consecutive_turns collapses same-speaker adjacent turns, so full
    # continuous coverage by one speaker should merge into exactly one turn —
    # confirms no gap (which would show up as two disjoint turns) and no
    # overlap (which _merge_consecutive_turns wouldn't produce either way,
    # but the total-duration check above already rules that out).
    assert len(turns) == 1
