#!/usr/bin/env python3
"""Measure preprocess_audio() wall-clock per step (no HTTP, no Whisper)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml
from dotenv import load_dotenv

from app.services.audio_processor import preprocess_audio
from app.services.upload_timing import UploadStepTimer
from benchmarks.stack_config import merge_stack_env, stack_env_to_preprocess_kwargs

load_dotenv()


def _load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark upload preprocess timing per step.")
    parser.add_argument("--stacks", default="benchmarks/stacks.yaml")
    parser.add_argument("--stack-id", default="spectral_hpf_agc_loudness_vad")
    parser.add_argument(
        "--audio",
        nargs="+",
        default=["uploads"],
        help="Audio file paths or directories to scan for mp3/wav/webm/mp4",
    )
    parser.add_argument("--output", default="benchmarks/results/upload-timing")
    parser.add_argument("--export-pcm", action="store_true", help="Include export_pcm step")
    args = parser.parse_args()

    config_path = (ROOT / args.stacks).resolve()
    config = _load_config(config_path)
    stacks: dict = config["stacks"]
    if args.stack_id not in stacks:
        print(f"Unknown stack id: {args.stack_id}", file=sys.stderr)
        return 1

    stack_env = merge_stack_env(stacks[args.stack_id])
    preprocess_kwargs = stack_env_to_preprocess_kwargs(stack_env)
    preprocess_kwargs["export_pcm_enabled"] = args.export_pcm

    audio_files: list[Path] = []
    for item in args.audio:
        path = Path(item)
        if not path.is_absolute():
            path = (ROOT / path).resolve()
        if path.is_file():
            audio_files.append(path)
        elif path.is_dir():
            for ext in ("*.mp3", "*.wav", "*.webm", "*.mp4"):
                audio_files.extend(sorted(path.glob(ext)))
        else:
            print(f"Skipping missing path: {path}", file=sys.stderr)

    if not audio_files:
        print("No audio files found.", file=sys.stderr)
        return 1

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (ROOT / args.output / timestamp).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "wav"
    work_dir.mkdir(parents=True, exist_ok=True)

    runs = []
    for audio_path in audio_files:
        print(f"Timing preprocess: {audio_path.name}")
        timer = UploadStepTimer(file_id=audio_path.stem)
        output_wav = work_dir / f"{audio_path.stem}.wav"
        processed = preprocess_audio(
            audio_path,
            output_wav,
            timing=timer,
            **preprocess_kwargs,
        )
        payload = timer.to_dict()
        payload["audio"] = str(audio_path.relative_to(ROOT) if audio_path.is_relative_to(ROOT) else audio_path)
        payload["stages"] = processed.get("stages", [])
        payload["duration_ms"] = processed.get("wav", {}).get("duration_ms")
        runs.append(payload)
        print(
            f"  total={payload['total_elapsed_s']:.2f}s "
            f"stages={payload['stages']}"
        )

    summary = {
        "timestamp": timestamp,
        "stack_id": args.stack_id,
        "stack_env": stack_env,
        "runs": runs,
    }
    summary_path = output_dir / "upload_timing_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {summary_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
