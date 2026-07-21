"""Rolling-window Sortformer diarization for a live audio stream.

Mirrors diarize_wav_sortformer_chunked's per-chunk loop body (same
_diarize_batch daemon call, same _match_local_to_global stitching), adapted
to a growing/rolling buffer instead of a complete pre-known file: each tick
diarizes the trailing (window_s + overlap_s) of buffered audio, stitches its
speaker labels onto the identities computed in the PREVIOUS tick (not just
the already-committed history — see _prev_tick_global_turns below) using the
shared overlap_s span, commits everything before that span (clipping, not
dropping, any turn that straddles the boundary so no audio's contribution is
ever silently lost), and keeps only the last overlap_s of audio buffered for
the next tick's matching context.

Known limitation carried over from the batch path: _match_local_to_global is
purely temporal-overlap based (no voice embeddings) — a speaker absent for
longer than overlap_s (e.g. steps out of the room) has no way to be
re-identified and will be assigned a new global id.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from app.services import wav_utils
from app.services.diarization_sortformer import (
    DEFAULT_MAX_DURATION_S,
    DEFAULT_MODEL_ID,
    _diarize_batch,
    _match_local_to_global,
    _merge_consecutive_turns,
)

SAMPLE_RATE = 16_000


class RealtimeDiarizationSession:
    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        device: str = "cuda",
        max_duration_s: float = DEFAULT_MAX_DURATION_S,
        min_turn_ms: int = 0,
        window_s: float = 30.0,
        overlap_s: float = 10.0,
        venv_python: Path | str | None = None,
        timeout_s: int = 60,
        use_daemon: bool = True,
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._max_duration_s = max_duration_s
        self._min_turn_ms = min_turn_ms
        self._window_s = window_s
        self._overlap_s = overlap_s
        self._venv_python = venv_python
        self._timeout_s = timeout_s
        self._use_daemon = use_daemon

        self._buffer = np.zeros(0, dtype=np.int16)
        self._buffer_start_ms = 0
        self._global_turns: list[dict[str, Any]] = []
        # Full (unclipped) global turns computed in the previous tick — kept
        # around purely to serve as matching context for the NEXT tick, since
        # a turn straddling the commit boundary is only partially committed
        # (see _commit_up_to below) but needs to be matched against in full.
        self._prev_tick_global_turns: list[dict[str, Any]] = []
        self._next_global_id = [0]
        self._first_tick = True

    def push_audio(self, pcm16_bytes: bytes) -> None:
        samples = np.frombuffer(pcm16_bytes, dtype=np.int16)
        self._buffer = np.concatenate([self._buffer, samples])

    def _buffer_duration_s(self) -> float:
        return len(self._buffer) / SAMPLE_RATE

    def _diarize_current_buffer(self) -> list[dict[str, Any]]:
        """Runs the daemon on the whole current buffer, returns turns rebased
        to absolute session ms (not yet stitched to global identities)."""
        with tempfile.TemporaryDirectory(prefix="phi-scribe-realtime-diar-") as tmp_dir:
            tmp_wav = Path(tmp_dir) / "window.wav"
            wav_utils.write_wav_slice(
                tmp_wav,
                self._buffer,
                start_ms=0,
                end_ms=int(self._buffer_duration_s() * 1000),
            )
            payload = _diarize_batch(
                [tmp_wav],
                model_id=self._model_id,
                device=self._device,
                max_duration_s=self._max_duration_s,
                min_turn_ms=self._min_turn_ms,
                venv_python=self._venv_python,
                timeout_s=self._timeout_s,
                batch_size=1,
                use_daemon=self._use_daemon,
            )
        raw_turns = payload["chunks"][0]["turns"]
        return [
            {
                "speaker": turn["speaker"],
                "start_ms": turn["start_ms"] + self._buffer_start_ms,
                "end_ms": turn["end_ms"] + self._buffer_start_ms,
            }
            for turn in raw_turns
        ]

    def _assign_global_turns(self, local_turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Maps this tick's local turns onto global speaker identities —
        first-appearance order on the very first tick (mirrors chunk 0 in
        diarize_wav_sortformer_chunked), overlap-matched against the previous
        tick's full turn set on every tick after."""
        if self._first_tick:
            first_local_to_global = {
                speaker: f"speaker_G{i}"
                for i, speaker in enumerate(sorted({t["speaker"] for t in local_turns}))
            }
            self._next_global_id = [len(first_local_to_global)]
            return [
                {"speaker": first_local_to_global[t["speaker"]], "start_ms": t["start_ms"], "end_ms": t["end_ms"]}
                for t in local_turns
            ]

        window_start_ms = self._buffer_start_ms
        window_end_ms = self._buffer_start_ms + int(self._overlap_s * 1000)
        mapping = _match_local_to_global(
            self._prev_tick_global_turns,
            local_turns,
            window_start_ms=window_start_ms,
            window_end_ms=window_end_ms,
            next_global_id=self._next_global_id,
        )
        return [
            {"speaker": mapping[t["speaker"]], "start_ms": t["start_ms"], "end_ms": t["end_ms"]}
            for t in local_turns
        ]

    def _commit_up_to(self, current_global_turns: list[dict[str, Any]], commit_before_ms: int) -> list[dict[str, Any]]:
        """Commits the portion of each turn that falls before commit_before_ms,
        clipping (not dropping) turns that straddle the boundary — the
        straddling remainder's audio is still in the retained buffer tail, so
        it gets picked up (matched back to the same global id) on a later tick."""
        newly_committed: list[dict[str, Any]] = []
        for turn in current_global_turns:
            if turn["start_ms"] >= commit_before_ms:
                continue
            committed_turn = {
                "speaker": turn["speaker"],
                "start_ms": turn["start_ms"],
                "end_ms": min(turn["end_ms"], commit_before_ms),
            }
            self._global_turns.append(committed_turn)
            newly_committed.append(committed_turn)
        return newly_committed

    def _advance_window(self, current_global_turns: list[dict[str, Any]]) -> None:
        self._prev_tick_global_turns = current_global_turns
        keep_from_sample = max(0, len(self._buffer) - int(self._overlap_s * SAMPLE_RATE))
        self._buffer = self._buffer[keep_from_sample:]
        self._buffer_start_ms += int(keep_from_sample / SAMPLE_RATE * 1000)
        self._first_tick = False
        self._global_turns.sort(key=lambda t: t["start_ms"])

    def maybe_diarize(self) -> list[dict[str, Any]] | None:
        """Diarizes the buffer once window_s of new audio has accumulated
        (beyond the overlap_s tail retained from the previous tick, on
        ticks after the first). Returns newly committed global turns, or
        None if not enough new audio yet."""
        required_s = self._window_s if self._first_tick else self._window_s + self._overlap_s
        if self._buffer_duration_s() < required_s:
            return None

        local_turns = self._diarize_current_buffer()
        buffer_end_ms = self._buffer_start_ms + int(self._buffer_duration_s() * 1000)
        commit_before_ms = buffer_end_ms - int(self._overlap_s * 1000)

        current_global_turns = self._assign_global_turns(local_turns)
        newly_committed = self._commit_up_to(current_global_turns, commit_before_ms)
        self._advance_window(current_global_turns)

        return newly_committed or None

    def finalize(self) -> dict[str, Any]:
        """Diarizes any remaining buffered audio (regardless of window_s),
        merges it fully into the global turns (no retained tail — there's no
        next tick), and returns the same shape
        diarize_wav_sortformer/diarize_wav_sortformer_chunked return."""
        if self._buffer_duration_s() > 0:
            local_turns = self._diarize_current_buffer()
            current_global_turns = self._assign_global_turns(local_turns)
            self._global_turns.extend(current_global_turns)
            self._global_turns.sort(key=lambda t: t["start_ms"])
            self._buffer = np.zeros(0, dtype=np.int16)

        merged_turns = _merge_consecutive_turns(self._global_turns)
        print(
            f"[diarization_realtime] session finalized: {len(merged_turns)} turn(s), "
            f"{len({t['speaker'] for t in merged_turns})} speaker(s)",
            file=sys.stderr,
        )
        return {
            "model": self._model_id,
            "min_turn_ms": self._min_turn_ms,
            "speakers": sorted({t["speaker"] for t in merged_turns}),
            "alignment_turns": [dict(t) for t in self._global_turns],
            "turns": merged_turns,
            "turn_count": len(merged_turns),
        }
