#!/usr/bin/env python3
"""Persistent Sortformer diarization daemon.

Keeps NeMo imported and the model loaded in GPU memory across many
diarization requests, instead of paying the ~4s NeMo import + ~1.6s model
load cost on every single call (as the one-shot benchmarks/sortformer_worker.py
does, invoked fresh per request). Runs as a subprocess, independent of the
main app's process lifecycle, so the loaded model survives app
restarts/reloads. nemo_toolkit lives in the same environment as the rest of
the app (requirements.txt) — no separate virtualenv needed.

Listens on a Unix domain socket, one request per connection. See
app/services/diarization_sortformer.py (_ensure_daemon, _daemon_request) for
the client side, which auto-starts this daemon on first use and falls back to
the one-shot sortformer_worker.py subprocess if the daemon can't be reached.

Wire protocol: 4-byte big-endian length prefix + UTF-8 JSON, both directions.
    request:  {"wav_paths": [...], "max_duration_s": 300.0, "min_turn_ms": 400,
               "batch_size": 1}
    response: {"chunks": [...], "load_s", "infer_s", "peak_vram_mb", "batch_size"}
              or {"error": "..."}

Usage:
    python3 benchmarks/sortformer_daemon.py \
        --socket /tmp/phi-scribe-sortformer-<key>.sock \
        --model-id nvidia/diar_sortformer_4spk-v1 --device cuda \
        [--idle-timeout-s 1800]

Exits automatically after --idle-timeout-s seconds with no requests, freeing
GPU memory rather than holding it forever on a memory-constrained card.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import struct
import sys
import time
import wave


def _audio_duration_s(wav_path: str) -> float:
    with wave.open(wav_path, "rb") as wav_file:
        return wav_file.getnframes() / wav_file.getframerate()


def _parse_segment(seg: str) -> tuple[float, float, str]:
    start_s, end_s, speaker = seg.split()
    return float(start_s), float(end_s), speaker


def _recv_exact(conn: socket.socket, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = conn.recv(remaining)
        if not chunk:
            raise ConnectionError("peer closed before sending a full message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_msg(conn: socket.socket) -> dict:
    (length,) = struct.unpack(">I", _recv_exact(conn, 4))
    return json.loads(_recv_exact(conn, length).decode("utf-8"))


def _send_msg(conn: socket.socket, obj: dict) -> None:
    body = json.dumps(obj).encode("utf-8")
    conn.sendall(struct.pack(">I", len(body)) + body)


def _diarize_request(diar_model, torch_module, model_id: str, request: dict) -> dict:
    wav_paths = request["wav_paths"]
    max_duration_s = float(request.get("max_duration_s", 300.0))
    min_turn_ms = int(request.get("min_turn_ms", 0))
    batch_size = max(1, min(int(request.get("batch_size", 1)), len(wav_paths)))

    for wav_path in wav_paths:
        duration_s = _audio_duration_s(wav_path)
        if duration_s > max_duration_s:
            return {
                "error": (
                    f"audio_too_long: {wav_path} is {duration_s:.1f}s, exceeds "
                    f"max_duration_s={max_duration_s:.1f}s."
                ),
            }

    use_cuda = next(diar_model.parameters()).is_cuda
    if use_cuda:
        torch_module.cuda.reset_peak_memory_stats()

    t1 = time.perf_counter()
    try:
        with torch_module.inference_mode(), contextlib.redirect_stdout(sys.stderr):
            predicted = diar_model.diarize(audio=wav_paths, batch_size=batch_size)
    except torch_module.cuda.OutOfMemoryError as exc:
        return {"error": f"cuda_out_of_memory: {exc}"}
    infer_s = time.perf_counter() - t1
    peak_vram_mb = (torch_module.cuda.max_memory_allocated() / (1024 * 1024)) if use_cuda else None

    chunks = []
    for wav_path, segments in zip(wav_paths, predicted):
        turns = []
        for seg in segments:
            start_s, end_s, speaker = _parse_segment(seg)
            start_ms, end_ms = int(start_s * 1000), int(end_s * 1000)
            if end_ms - start_ms < min_turn_ms:
                continue
            turns.append({"speaker": speaker, "start_ms": start_ms, "end_ms": end_ms})
        turns.sort(key=lambda t: t["start_ms"])
        chunks.append({
            "model": model_id,
            "min_turn_ms": min_turn_ms,
            "speakers": sorted({t["speaker"] for t in turns}),
            "turns": turns,
            "turn_count": len(turns),
            "audio_duration_s": round(_audio_duration_s(wav_path), 1),
        })

    return {
        "chunks": chunks,
        "infer_s": round(infer_s, 2),
        "peak_vram_mb": peak_vram_mb,
        "batch_size": batch_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--model-id", default="nvidia/diar_sortformer_4spk-v1")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--idle-timeout-s", type=float, default=1800.0)
    args = parser.parse_args()

    with contextlib.suppress(FileNotFoundError):
        os.remove(args.socket)

    print(f"[daemon] loading {args.model_id} on {args.device}...", file=sys.stderr)
    t0 = time.perf_counter()
    import torch
    from nemo.collections.asr.models import SortformerEncLabelModel

    with contextlib.redirect_stdout(sys.stderr):
        diar_model = SortformerEncLabelModel.from_pretrained(args.model_id)
        diar_model = diar_model.to(args.device)
        diar_model.eval()
    load_s = time.perf_counter() - t0
    print(f"[daemon] model loaded in {load_s:.1f}s, listening on {args.socket}", file=sys.stderr)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(args.socket)
    server.listen(1)
    server.settimeout(1.0)  # lets the accept loop check the idle timeout periodically

    last_request_at = time.monotonic()
    try:
        while time.monotonic() - last_request_at <= args.idle_timeout_s:
            try:
                conn, _addr = server.accept()
            except socket.timeout:
                continue
            with conn:
                try:
                    request = _recv_msg(conn)
                    response = _diarize_request(diar_model, torch, args.model_id, request)
                    response.setdefault("load_s", round(load_s, 2))
                    _send_msg(conn, response)
                except Exception as exc:
                    # The daemon serves many requests over its lifetime — one bad
                    # request must not take the whole process down.
                    with contextlib.suppress(Exception):
                        _send_msg(conn, {"error": f"daemon_request_failed: {exc}"})
                    print(f"[daemon] request failed: {exc}", file=sys.stderr)
            last_request_at = time.monotonic()
        print(f"[daemon] idle for {args.idle_timeout_s:.0f}s, shutting down", file=sys.stderr)
    finally:
        server.close()
        with contextlib.suppress(FileNotFoundError):
            os.remove(args.socket)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
