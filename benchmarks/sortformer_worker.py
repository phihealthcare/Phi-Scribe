#!/usr/bin/env python3
"""Standalone Sortformer (nvidia/diar_sortformer_4spk-v1) diarization worker.

Run as a subprocess (see app/services/diarization_sortformer.py) rather than
imported in-process, so the persistent daemon (sortformer_daemon.py) can keep
NeMo/the model loaded independently of the main app's process lifecycle.
nemo_toolkit lives in the same environment as the rest of the app
(requirements.txt) — no separate virtualenv needed.

Usage:
    python3 benchmarks/sortformer_worker.py <wav_path> [<wav_path> ...] \
        [--max-duration-s 300] [--device cuda] [--min-turn-ms 0] [--batch-size 1]

Accepts one or more WAV paths (chunking a long recording into several shorter
clips that each fit under SORTFORMER_MAX_DURATION_S). The model is loaded
once, then all paths are diarized via a SINGLE `diar_model.diarize()` call
(NeMo natively accepts a list of paths + batch_size) instead of one Python
call per file. batch_size defaults to 1: measured empirically, batch_size=2
didn't reduce inference time at all on this workload but roughly doubled
peak VRAM (2.8GB vs 1.7GB for a 5-chunk/180s run) — so there's no reason to
raise it above 1 unless a future GPU/workload shows an actual speed benefit
worth the extra memory.

Prints ONE JSON object to stdout:
    {"chunks": [<one result per input path, in order>], "load_s", "infer_s",
     "peak_vram_mb", "batch_size"}
or {"error": "..."} on failure (also on stdout, so the caller only has to
parse one stream). All logs/progress from NeMo go to stderr.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
import wave


def _audio_duration_s(wav_path: str) -> float:
    with wave.open(wav_path, "rb") as wav_file:
        return wav_file.getnframes() / wav_file.getframerate()


def _parse_segment(seg: str) -> tuple[float, float, str]:
    # Observed format from SortformerEncLabelModel.diarize(): "0.000 3.200 speaker_0"
    start_s, end_s, speaker = seg.split()
    return float(start_s), float(end_s), speaker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav_paths", nargs="+")
    parser.add_argument("--model-id", default="nvidia/diar_sortformer_4spk-v1")
    parser.add_argument("--max-duration-s", type=float, default=300.0)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--min-turn-ms", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=1)
    args = parser.parse_args()

    for wav_path in args.wav_paths:
        duration_s = _audio_duration_s(wav_path)
        if duration_s > args.max_duration_s:
            print(json.dumps({
                "error": (
                    f"audio_too_long: {wav_path} is {duration_s:.1f}s, exceeds "
                    f"SORTFORMER_MAX_DURATION_S={args.max_duration_s:.1f}s. Each chunk must "
                    "individually fit under the ceiling."
                ),
            }))
            return 1

    import torch
    from nemo.collections.asr.models import SortformerEncLabelModel

    print(f"[worker] loading {args.model_id} on {args.device}...", file=sys.stderr)
    t0 = time.perf_counter()
    # NeMo prints a large config dump to stdout on load; redirect it to stderr
    # so stdout stays parseable as a single JSON object.
    with contextlib.redirect_stdout(sys.stderr):
        diar_model = SortformerEncLabelModel.from_pretrained(args.model_id)
        diar_model = diar_model.to(args.device)
        diar_model.eval()
    load_s = time.perf_counter() - t0
    print(f"[worker] model loaded in {load_s:.1f}s", file=sys.stderr)

    use_cuda = args.device == "cuda" and torch.cuda.is_available()
    if use_cuda:
        torch.cuda.reset_peak_memory_stats()

    batch_size = max(1, min(args.batch_size, len(args.wav_paths)))
    print(
        f"[worker] diarizing {len(args.wav_paths)} file(s) in one batched call (batch_size={batch_size})...",
        file=sys.stderr,
    )
    t1 = time.perf_counter()
    try:
        with torch.inference_mode(), contextlib.redirect_stdout(sys.stderr):
            predicted = diar_model.diarize(audio=args.wav_paths, batch_size=batch_size)
    except torch.cuda.OutOfMemoryError as exc:
        print(json.dumps({"error": f"cuda_out_of_memory: {exc}"}))
        return 1
    infer_s = time.perf_counter() - t1
    peak_vram_mb = (torch.cuda.max_memory_allocated() / (1024 * 1024)) if use_cuda else None
    print(f"[worker] batch diarize done in {infer_s:.2f}s, peak VRAM {peak_vram_mb} MB", file=sys.stderr)

    chunks = []
    for wav_path, segments in zip(args.wav_paths, predicted):
        turns = []
        for seg in segments:
            start_s, end_s, speaker = _parse_segment(seg)
            start_ms, end_ms = int(start_s * 1000), int(end_s * 1000)
            if end_ms - start_ms < args.min_turn_ms:
                continue
            turns.append({"speaker": speaker, "start_ms": start_ms, "end_ms": end_ms})
        turns.sort(key=lambda t: t["start_ms"])
        chunks.append({
            "model": args.model_id,
            "min_turn_ms": args.min_turn_ms,
            "speakers": sorted({t["speaker"] for t in turns}),
            "turns": turns,
            "turn_count": len(turns),
            "audio_duration_s": round(_audio_duration_s(wav_path), 1),
        })

    result = {
        "chunks": chunks,
        "load_s": round(load_s, 2),
        "infer_s": round(infer_s, 2),
        "peak_vram_mb": peak_vram_mb,
        "batch_size": batch_size,
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
