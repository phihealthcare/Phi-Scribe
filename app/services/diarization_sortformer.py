"""Sortformer (nvidia/diar_sortformer_4spk-v1) diarization — the only
diarization backend in this app (pyannote.audio was removed; NeMo used to be
isolated in a separate .venv-sortformer/ purely because NeMo's dependency
tree conflicted with pyannote.audio installed in the same environment —
that reason no longer applies now that pyannote is gone).

This module deliberately does NOT import nemo/torch-for-nemo directly.
Sortformer runs as a subprocess (see benchmarks/sortformer_worker.py /
sortformer_daemon.py) — this file is just the bridge that shells out and
parses the result. The subprocess boundary is kept independent of which venv
supplies the interpreter (see DEFAULT_VENV_PYTHON) because it also provides
GPU-memory eviction (the daemon frees VRAM by exiting after an idle timeout)
and crash isolation (a NeMo/CUDA crash only kills the disposable subprocess),
not just dependency isolation.
"""
from __future__ import annotations

import hashlib
import json
import socket
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

from app.services import wav_utils

ROOT = Path(__file__).resolve().parents[2]
# NeMo's deps now live in the main venv (see requirements.txt) — the daemon
# subprocess just uses whichever interpreter is running this code. Override
# via SORTFORMER_VENV_PYTHON if you ever need a different interpreter again.
DEFAULT_VENV_PYTHON = Path(sys.executable)
WORKER_SCRIPT = ROOT / "benchmarks" / "sortformer_worker.py"
DAEMON_SCRIPT = ROOT / "benchmarks" / "sortformer_daemon.py"
DEFAULT_MODEL_ID = "nvidia/diar_sortformer_4spk-v1"
DEFAULT_MAX_DURATION_S = 300.0  # empirically found ceiling on a 6GB GPU — see plan notes
DEFAULT_CHUNK_S = 240.0
DEFAULT_CHUNK_OVERLAP_S = 20.0

# Persistent-daemon settings (see sortformer_daemon.py). Keeping NeMo imported
# and the model loaded in GPU memory across requests avoids paying the ~4s
# import + ~1.6s model-load cost on every single diarization call — measured
# to be the dominant fixed cost, well above anything WAV I/O or batching could
# shave off. If the daemon can't be started/reached for any reason, callers
# transparently fall back to the one-shot sortformer_worker.py subprocess.
DAEMON_STARTUP_TIMEOUT_S = 60.0
DAEMON_IDLE_TIMEOUT_S = 1800.0
DAEMON_POLL_INTERVAL_S = 0.2


def _merge_consecutive_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not turns:
        return []
    merged: list[dict[str, Any]] = [dict(turns[0])]
    for turn in turns[1:]:
        if turn["speaker"] == merged[-1]["speaker"]:
            merged[-1]["end_ms"] = max(merged[-1]["end_ms"], turn["end_ms"])
        else:
            merged.append(dict(turn))
    return merged


def _wav_duration_s(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as wav_file:
        return wav_file.getnframes() / wav_file.getframerate()


def _run_worker(
    wav_paths: list[Path],
    *,
    model_id: str,
    device: str,
    max_duration_s: float,
    min_turn_ms: int,
    venv_python: Path | str | None,
    timeout_s: int,
    batch_size: int = 1,
) -> dict[str, Any]:
    """Invokes the worker once for all wav_paths (model loaded a single time,
    all paths diarized in one batched diar_model.diarize() call — see
    sortformer_worker.py). Returns the full payload:
    {"chunks": [...], "load_s", "infer_s", "peak_vram_mb", "batch_size"}."""
    python_bin = Path(venv_python) if venv_python else DEFAULT_VENV_PYTHON
    if not python_bin.is_file():
        raise RuntimeError(
            f"Sortformer venv not found at {python_bin}. Create it with: "
            f"python3 -m venv .venv-sortformer && .venv-sortformer/bin/pip install nemo_toolkit[asr]"
        )
    if not WORKER_SCRIPT.is_file():
        raise RuntimeError(f"Sortformer worker script not found: {WORKER_SCRIPT}")

    cmd = [
        str(python_bin),
        str(WORKER_SCRIPT),
        *(str(p) for p in wav_paths),
        "--model-id", model_id,
        "--max-duration-s", str(max_duration_s),
        "--device", device,
        "--min-turn-ms", str(min_turn_ms),
        "--batch-size", str(batch_size),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)

    stdout_lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not stdout_lines:
        raise RuntimeError(
            f"Sortformer worker produced no output (exit code {proc.returncode}). "
            f"stderr tail: {proc.stderr[-2000:]}"
        )
    try:
        payload = json.loads(stdout_lines[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Sortformer worker returned non-JSON output: {stdout_lines[-1][:500]!r}. "
            f"stderr tail: {proc.stderr[-2000:]}"
        ) from exc

    if "error" in payload:
        raise RuntimeError(f"Sortformer worker error: {payload['error']}")
    if payload.get("chunks") is None:
        raise RuntimeError(f"Sortformer worker output missing 'chunks': {payload}")
    return payload


def _daemon_socket_path(model_id: str, device: str) -> Path:
    # Keyed by model_id+device so different combos never collide on one
    # daemon (each gets its own persistent process/socket automatically).
    key = hashlib.sha1(f"{model_id}:{device}".encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"phi-scribe-sortformer-{key}.sock"


def _daemon_is_alive(socket_path: Path) -> bool:
    if not socket_path.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1.0)
            probe.connect(str(socket_path))
        return True
    except OSError:
        return False


def _start_daemon(socket_path: Path, *, model_id: str, device: str, venv_python: Path | str | None) -> None:
    python_bin = Path(venv_python) if venv_python else DEFAULT_VENV_PYTHON
    if not python_bin.is_file():
        raise RuntimeError(f"Sortformer venv not found at {python_bin}")
    if not DAEMON_SCRIPT.is_file():
        raise RuntimeError(f"Sortformer daemon script not found: {DAEMON_SCRIPT}")

    log_path = Path(tempfile.gettempdir()) / f"{socket_path.stem}.log"
    cmd = [
        str(python_bin), str(DAEMON_SCRIPT),
        "--socket", str(socket_path),
        "--model-id", model_id,
        "--device", device,
        "--idle-timeout-s", str(DAEMON_IDLE_TIMEOUT_S),
    ]
    with open(log_path, "a") as log_file:
        subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,  # survives the caller's process exiting/reloading
        )
    print(f"[diarization_sortformer] starting daemon (log: {log_path})...", file=sys.stderr)


def _ensure_daemon(socket_path: Path, *, model_id: str, device: str, venv_python: Path | str | None) -> None:
    if _daemon_is_alive(socket_path):
        return
    _start_daemon(socket_path, model_id=model_id, device=device, venv_python=venv_python)
    deadline = time.monotonic() + DAEMON_STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if _daemon_is_alive(socket_path):
            return
        time.sleep(DAEMON_POLL_INTERVAL_S)
    raise RuntimeError(f"Sortformer daemon did not become ready within {DAEMON_STARTUP_TIMEOUT_S:.0f}s")


def _daemon_request(socket_path: Path, request: dict[str, Any], *, timeout_s: int) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout_s)
        conn.connect(str(socket_path))
        body = json.dumps(request).encode("utf-8")
        conn.sendall(struct.pack(">I", len(body)) + body)
        (length,) = struct.unpack(">I", _recv_exact(conn, 4))
        payload = json.loads(_recv_exact(conn, length).decode("utf-8"))
    if "error" in payload:
        raise RuntimeError(f"Sortformer daemon error: {payload['error']}")
    if payload.get("chunks") is None:
        raise RuntimeError(f"Sortformer daemon output missing 'chunks': {payload}")
    return payload


def _recv_exact(conn: socket.socket, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = conn.recv(remaining)
        if not chunk:
            raise ConnectionError("Sortformer daemon closed the connection before responding")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _diarize_batch(
    wav_paths: list[Path],
    *,
    model_id: str,
    device: str,
    max_duration_s: float,
    min_turn_ms: int,
    venv_python: Path | str | None,
    timeout_s: int,
    batch_size: int = 1,
    use_daemon: bool = True,
) -> dict[str, Any]:
    """Diarizes wav_paths, preferring the persistent daemon (no import/model-load
    cost after the first call) and transparently falling back to the one-shot
    sortformer_worker.py subprocess if the daemon can't be started or reached."""
    if use_daemon:
        socket_path = _daemon_socket_path(model_id, device)
        try:
            _ensure_daemon(socket_path, model_id=model_id, device=device, venv_python=venv_python)
            return _daemon_request(
                socket_path,
                {
                    "wav_paths": [str(p) for p in wav_paths],
                    "max_duration_s": max_duration_s,
                    "min_turn_ms": min_turn_ms,
                    "batch_size": batch_size,
                },
                timeout_s=timeout_s,
            )
        except Exception as exc:
            print(
                f"[diarization_sortformer] daemon unavailable ({exc}); "
                "falling back to one-shot subprocess",
                file=sys.stderr,
            )

    return _run_worker(
        wav_paths,
        model_id=model_id,
        device=device,
        max_duration_s=max_duration_s,
        min_turn_ms=min_turn_ms,
        venv_python=venv_python,
        timeout_s=timeout_s,
        batch_size=batch_size,
    )


def diarize_wav_sortformer(
    wav_path: Path,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    max_duration_s: float = DEFAULT_MAX_DURATION_S,
    device: str = "cuda",
    min_turn_ms: int = 0,
    venv_python: Path | str | None = None,
    timeout_s: int = 600,
    use_daemon: bool = True,
) -> dict[str, Any]:
    """Same return shape as diarization.diarize_wav, so callers (e.g.
    transcribe_diarized.py) don't need to care which backend produced it:
    {"model", "min_turn_ms", "speakers": [...], "alignment_turns": [...],
     "turns": [...], "turn_count": N}

    Only safe for audio that fits under max_duration_s in a single pass — use
    diarize_wav_sortformer_chunked for longer recordings.
    """
    payload = _diarize_batch(
        [wav_path],
        model_id=model_id,
        device=device,
        max_duration_s=max_duration_s,
        min_turn_ms=min_turn_ms,
        venv_python=venv_python,
        timeout_s=timeout_s,
        batch_size=1,
        use_daemon=use_daemon,
    )
    result = payload["chunks"][0]

    alignment_turns = [dict(turn) for turn in result["turns"]]
    merged_turns = _merge_consecutive_turns(sorted(alignment_turns, key=lambda t: t["start_ms"]))

    print(
        f"[diarization_sortformer] {wav_path.name}: "
        f"infer={payload['infer_s']}s peak_vram={payload['peak_vram_mb']}MB",
        file=sys.stderr,
    )

    return {
        "model": result["model"],
        "min_turn_ms": min_turn_ms,
        "speakers": sorted({t["speaker"] for t in merged_turns}),
        "alignment_turns": alignment_turns,
        "turns": merged_turns,
        "turn_count": len(merged_turns),
        "sortformer_timing": {
            "infer_s": payload["infer_s"],
            "peak_vram_mb": payload["peak_vram_mb"],
            "load_s": payload["load_s"],
        },
    }


def _chunk_boundaries(duration_s: float, chunk_s: float, overlap_s: float) -> list[tuple[float, float]]:
    step = chunk_s - overlap_s
    boundaries: list[tuple[float, float]] = []
    start = 0.0
    while start < duration_s:
        end = min(start + chunk_s, duration_s)
        boundaries.append((start, end))
        if end >= duration_s:
            break
        start += step
    return boundaries


def _overlap_ms(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def _match_local_to_global(
    prev_global_turns: list[dict[str, Any]],
    curr_local_turns: list[dict[str, Any]],
    *,
    window_start_ms: int,
    window_end_ms: int,
    next_global_id: list[int],
) -> dict[str, str]:
    """Greedy overlap-based matching of curr chunk's raw speaker_N labels onto
    already-established global speaker identities, using only the shared
    overlap window between the two adjacent chunks. A curr-chunk speaker with
    no clear temporal overlap with any previously-known speaker gets assigned
    a brand new global identity."""
    overlap_matrix: dict[tuple[str, str], int] = {}
    for p_turn in prev_global_turns:
        p_ov = _overlap_ms(p_turn["start_ms"], p_turn["end_ms"], window_start_ms, window_end_ms)
        if p_ov <= 0:
            continue
        for c_turn in curr_local_turns:
            c_ov = _overlap_ms(c_turn["start_ms"], c_turn["end_ms"], window_start_ms, window_end_ms)
            if c_ov <= 0:
                continue
            shared = _overlap_ms(p_turn["start_ms"], p_turn["end_ms"], c_turn["start_ms"], c_turn["end_ms"])
            if shared > 0:
                key = (p_turn["speaker"], c_turn["speaker"])
                overlap_matrix[key] = overlap_matrix.get(key, 0) + shared

    pairs = sorted(overlap_matrix.items(), key=lambda kv: kv[1], reverse=True)
    matched_prev: set[str] = set()
    matched_curr: set[str] = set()
    mapping: dict[str, str] = {}
    for (prev_global, curr_local), _shared in pairs:
        if prev_global in matched_prev or curr_local in matched_curr:
            continue
        mapping[curr_local] = prev_global
        matched_prev.add(prev_global)
        matched_curr.add(curr_local)

    for curr_local in sorted({t["speaker"] for t in curr_local_turns}):
        if curr_local not in mapping:
            mapping[curr_local] = f"speaker_G{next_global_id[0]}"
            next_global_id[0] += 1

    return mapping


def diarize_wav_sortformer_chunked(
    wav_path: Path,
    *,
    chunk_s: float = DEFAULT_CHUNK_S,
    overlap_s: float = DEFAULT_CHUNK_OVERLAP_S,
    model_id: str = DEFAULT_MODEL_ID,
    max_duration_s: float = DEFAULT_MAX_DURATION_S,
    device: str = "cuda",
    min_turn_ms: int = 0,
    venv_python: Path | str | None = None,
    timeout_s: int = 600,
    batch_size: int = 1,
    use_daemon: bool = True,
) -> dict[str, Any]:
    """Same return shape as diarize_wav_sortformer, but works on audio longer
    than max_duration_s by splitting it into overlapping chunks, diarizing
    each (model loaded once — see use_daemon below), and stitching speaker
    identities back together via temporal-overlap matching in each chunk
    boundary's shared window.

    use_daemon=True (default) reuses a persistent worker process across
    calls, avoiding the ~4s NeMo import + ~1.6s model-load cost on every
    request; it auto-starts on first use and falls back to the one-shot
    subprocess automatically if it can't be reached. See _diarize_batch.

    Does NOT fix the separate word-alignment merge fragmentation bug in
    transcribe_diarized.py — this only makes the diarization step itself
    cover the full recording. See the plan notes in
    ~/.claude/plans/como-eu-poderia-testar-mutable-scroll.md for the full
    design rationale and known caveats (untested stitching heuristic, model
    trained on ~90s sessions vs. 240s chunks here, etc).
    """
    duration_s = _wav_duration_s(wav_path)
    if duration_s <= max_duration_s:
        return diarize_wav_sortformer(
            wav_path,
            model_id=model_id,
            max_duration_s=max_duration_s,
            device=device,
            min_turn_ms=min_turn_ms,
            venv_python=venv_python,
            timeout_s=timeout_s,
            use_daemon=use_daemon,
        )

    boundaries = _chunk_boundaries(duration_s, chunk_s, overlap_s)

    # Read the source WAV once — extract_turn_wav() would otherwise re-read
    # the whole file from disk per chunk, which gets expensive on long
    # recordings (e.g. ~23 chunks for a 60min consultation).
    audio, _sample_rate = wav_utils.read_wav(wav_path)

    with tempfile.TemporaryDirectory(prefix="phi-scribe-sortformer-chunks-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        chunk_wav_paths = []
        for index, (start_s, end_s) in enumerate(boundaries):
            chunk_wav = tmp_path / f"chunk_{index:02d}.wav"
            wav_utils.write_wav_slice(
                chunk_wav,
                audio,
                start_ms=int(start_s * 1000),
                end_ms=int(end_s * 1000),
            )
            chunk_wav_paths.append(chunk_wav)

        payload = _diarize_batch(
            chunk_wav_paths,
            model_id=model_id,
            device=device,
            max_duration_s=max_duration_s,
            min_turn_ms=min_turn_ms,
            venv_python=venv_python,
            timeout_s=timeout_s * max(1, len(chunk_wav_paths)),
            batch_size=batch_size,
            use_daemon=use_daemon,
        )
    raw_chunks = payload["chunks"]

    # Rebase each chunk's turns from chunk-local to global timestamps.
    rebased_chunks: list[list[dict[str, Any]]] = []
    for (start_s, _end_s), raw in zip(boundaries, raw_chunks):
        offset_ms = int(start_s * 1000)
        rebased_chunks.append([
            {"speaker": t["speaker"], "start_ms": t["start_ms"] + offset_ms, "end_ms": t["end_ms"] + offset_ms}
            for t in raw["turns"]
        ])

    # Chunk 0 defines the initial global identities directly (appearance order).
    first_local_to_global = {
        speaker: f"speaker_G{i}"
        for i, speaker in enumerate(sorted({t["speaker"] for t in rebased_chunks[0]}))
    }
    next_global_id = [len(first_local_to_global)]
    global_chunks: list[list[dict[str, Any]]] = [
        [
            {"speaker": first_local_to_global[t["speaker"]], "start_ms": t["start_ms"], "end_ms": t["end_ms"]}
            for t in rebased_chunks[0]
        ]
    ]

    for i in range(1, len(rebased_chunks)):
        prev_global_turns = global_chunks[i - 1]
        curr_local_turns = rebased_chunks[i]
        # Shared overlap window in global ms between chunk i-1 and chunk i.
        window_start_ms = int(boundaries[i][0] * 1000)
        window_end_ms = int(boundaries[i - 1][1] * 1000)

        mapping = _match_local_to_global(
            prev_global_turns,
            curr_local_turns,
            window_start_ms=window_start_ms,
            window_end_ms=window_end_ms,
            next_global_id=next_global_id,
        )
        global_chunks.append([
            {"speaker": mapping[t["speaker"]], "start_ms": t["start_ms"], "end_ms": t["end_ms"]}
            for t in curr_local_turns
        ])

    # Clip each chunk to its own non-overlapping time range, cutting overlaps
    # at the midpoint, so seams don't duplicate or conflict.
    combined_turns: list[dict[str, Any]] = []
    for i, turns in enumerate(global_chunks):
        keep_start_ms = 0
        if i > 0:
            ov_start, ov_end = boundaries[i][0], boundaries[i - 1][1]
            keep_start_ms = int(((ov_start + ov_end) / 2) * 1000)
        keep_end_ms = int(duration_s * 1000)
        if i < len(global_chunks) - 1:
            ov_start, ov_end = boundaries[i + 1][0], boundaries[i][1]
            keep_end_ms = int(((ov_start + ov_end) / 2) * 1000)

        for turn in turns:
            clipped_start = max(turn["start_ms"], keep_start_ms)
            clipped_end = min(turn["end_ms"], keep_end_ms)
            if clipped_end > clipped_start:
                combined_turns.append({"speaker": turn["speaker"], "start_ms": clipped_start, "end_ms": clipped_end})

    combined_turns.sort(key=lambda t: t["start_ms"])
    merged_turns = _merge_consecutive_turns(combined_turns)

    # infer_s/peak_vram_mb now cover the ONE batched diar_model.diarize() call
    # across all chunks, not a per-chunk sum (see sortformer_worker.py).
    total_infer_s = payload["infer_s"]
    peak_vram_mb = payload["peak_vram_mb"] or 0

    print(
        f"[diarization_sortformer] {wav_path.name}: chunked into {len(boundaries)} piece(s) "
        f"({chunk_s:.0f}s chunk / {overlap_s:.0f}s overlap, batch_size={payload['batch_size']}), "
        f"infer={total_infer_s:.2f}s peak_vram={peak_vram_mb:.0f}MB",
        file=sys.stderr,
    )

    return {
        "model": raw_chunks[0]["model"],
        "min_turn_ms": min_turn_ms,
        "speakers": sorted({t["speaker"] for t in merged_turns}),
        "alignment_turns": combined_turns,
        "turns": merged_turns,
        "turn_count": len(merged_turns),
        "sortformer_timing": {
            "load_s": payload["load_s"],
            "total_infer_s": round(total_infer_s, 2),
            "peak_vram_mb": peak_vram_mb,
            "chunk_count": len(boundaries),
            "batch_size": payload["batch_size"],
        },
        "chunking": {
            "chunk_s": chunk_s,
            "overlap_s": overlap_s,
            "boundaries": boundaries,
        },
    }
