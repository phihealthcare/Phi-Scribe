#!/usr/bin/env python3
"""Compare upload Silero VAD vs faster-whisper vad_filter (time + WER/CER)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml
from dotenv import load_dotenv

from app.services.audio_processor import preprocess_audio
from app.services.transcribe import transcribe_options_from_mapping, transcribe_wav
from app.services.upload_timing import UploadStepTimer
from benchmarks.score import load_reference_text, score_transcript
from benchmarks.stack_config import merge_stack_env, resolve_whisper_block, stack_env_to_preprocess_kwargs

load_dotenv()


def _load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _merge_whisper(base: dict, overrides: dict) -> dict:
    merged = dict(base)
    merged.update(overrides or {})
    return merged


def _run_variant(
    *,
    variant_id: str,
    description: str,
    stack_env: dict,
    whisper_cfg: dict,
    audio_path: Path,
    work_dir: Path,
    reference_text: str,
) -> dict:
    output_wav = work_dir / f"{variant_id}.wav"
    timer = UploadStepTimer(file_id=variant_id)

    t_preprocess = time.perf_counter()
    processed = preprocess_audio(
        audio_path,
        output_wav,
        timing=timer,
        **stack_env_to_preprocess_kwargs(stack_env),
    )
    preprocess_s = time.perf_counter() - t_preprocess

    timing = timer.to_dict()
    vad_meta = processed.get("vad")
    wav_meta = processed.get("wav", {})

    t_transcribe = time.perf_counter()
    transcription = transcribe_wav(output_wav, **transcribe_options_from_mapping(whisper_cfg))
    transcribe_s = time.perf_counter() - t_transcribe

    raw_text = str(transcription.get("text", ""))
    scores = score_transcript(reference_text, raw_text)

    vad_step_s = None
    for step in timing.get("steps", []):
        step_name = step.get("name") or step.get("step")
        if step_name == "vad":
            vad_step_s = step.get("duration_s")
            break

    # Effective speech length Whisper decoded (after its internal VAD, if any).
    speech_ms = transcription.get("duration_after_vad_ms")
    if speech_ms is None:
        speech_ms = transcription.get("duration_ms")
    # Upload Silero rewrites the WAV — prefer trimmed duration when present.
    if vad_meta and vad_meta.get("trimmed_duration_ms") is not None:
        wav_speech_ms = vad_meta["trimmed_duration_ms"]
    else:
        wav_speech_ms = wav_meta.get("duration_ms")

    return {
        "variant_id": variant_id,
        "description": description,
        "stack_env": stack_env,
        "whisper": whisper_cfg,
        "stages": processed.get("stages", []),
        "timing": {
            "preprocess_s": round(preprocess_s, 3),
            "vad_step_s": vad_step_s,
            "transcribe_s": round(transcribe_s, 3),
            "total_s": round(preprocess_s + transcribe_s, 3),
            "upload_timing": timing,
        },
        "audio_duration_ms": wav_meta.get("duration_ms"),
        "wav_speech_ms": wav_speech_ms,
        "whisper_duration_ms": transcription.get("duration_ms"),
        "whisper_duration_after_vad_ms": transcription.get("duration_after_vad_ms"),
        "effective_speech_ms": speech_ms,
        "vad": vad_meta,
        "scores_raw": scores,
        "text_preview": raw_text[:500] + ("…" if len(raw_text) > 500 else ""),
    }


def _write_markdown(path: Path, *, config_path: Path, results: list[dict], reference_path: Path) -> None:
    lines = [
        "# VAD comparison — consulta-real-1",
        "",
        f"- **Config:** `{config_path.relative_to(ROOT)}`",
        f"- **Audio:** `{results[0].get('audio', 'public/consulta-real-1.mp4')}`",
        f"- **Reference:** `{reference_path.relative_to(ROOT)}`",
        "",
        "## Summary",
        "",
        "| Variant | Upload VAD | Whisper vad_filter | Preprocess (s) | WAV speech (min) | Whisper after VAD (min) | Transcribe (s) | Total (s) | WER raw | CER raw |",
        "|---------|------------|-------------------|----------------|------------------|-------------------------|----------------|-----------|---------|---------|",
    ]
    for row in results:
        stack = row["stack_env"]
        whisper = row["whisper"]
        t = row["timing"]
        s = row["scores_raw"]

        def _min(ms: int | float | None) -> str:
            if ms is None:
                return "—"
            return f"{ms / 60000:.2f}"

        lines.append(
            f"| `{row['variant_id']}` "
            f"| {'yes' if stack.get('VAD_ENABLED') else 'no'} "
            f"| {'yes' if whisper.get('vad_filter') else 'no'} "
            f"| {t['preprocess_s']} "
            f"| {_min(row.get('wav_speech_ms'))} "
            f"| {_min(row.get('whisper_duration_after_vad_ms') or row.get('effective_speech_ms'))} "
            f"| {t['transcribe_s']} "
            f"| {t['total_s']} "
            f"| {s['wer_percent']}% "
            f"| {s['cer_percent']}% |"
        )

    if len(results) >= 2:
        baseline = results[0]
        for row in results[1:]:
            delta_wer = round(row["scores_raw"]["wer_percent"] - baseline["scores_raw"]["wer_percent"], 2)
            delta_total = round(row["timing"]["total_s"] - baseline["timing"]["total_s"], 2)
            lines.extend(
                [
                    "",
                    f"### `{row['variant_id']}` vs `{baseline['variant_id']}`",
                    "",
                    f"- Δ total time: **{delta_total:+.2f}s**",
                    f"- Δ WER: **{delta_wer:+.2f} pp**",
                    f"- Δ CER: **{round(row['scores_raw']['cer_percent'] - baseline['scores_raw']['cer_percent'], 2):+.2f} pp**",
                ]
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Silero upload VAD vs Whisper vad_filter.")
    parser.add_argument("--config", default="benchmarks/vad_compare_consulta-real-1.yaml")
    parser.add_argument("--only", help="Comma-separated variant ids")
    parser.add_argument("--output", help="Output directory")
    args = parser.parse_args()

    config_path = (ROOT / args.config).resolve()
    config = _load_config(config_path)
    audio_path = (ROOT / config["audio"]).resolve()
    reference_path = (ROOT / config["reference"]).resolve()
    if not audio_path.is_file():
        print(f"Audio not found: {audio_path}", file=sys.stderr)
        return 1
    if not reference_path.is_file():
        print(f"Reference not found: {reference_path}", file=sys.stderr)
        return 1

    reference_text = load_reference_text(reference_path)
    whisper_base = resolve_whisper_block(config["whisper"])
    base_stack = merge_stack_env(config.get("base_stack") or {})
    variants: dict = config["variants"]

    selected = list(variants.keys())
    if args.only:
        selected = [item.strip() for item in args.only.split(",") if item.strip()]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        Path(args.output).resolve()
        if args.output
        else ROOT / "benchmarks/results/vad-compare-consulta-real-1" / timestamp
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "wav"
    work_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for variant_id in selected:
        if variant_id not in variants:
            print(f"Unknown variant: {variant_id}", file=sys.stderr)
            return 1
        variant = variants[variant_id]
        stack_env = {**base_stack, **(variant.get("stack_overrides") or {})}
        whisper_cfg = _merge_whisper(whisper_base, variant.get("whisper_overrides") or {})
        print(f"\n=== {variant_id}: {variant.get('description', '')} ===")
        print(f"  VAD_ENABLED={stack_env.get('VAD_ENABLED')}  vad_filter={whisper_cfg.get('vad_filter')}")

        result = _run_variant(
            variant_id=variant_id,
            description=str(variant.get("description", "")),
            stack_env=stack_env,
            whisper_cfg=whisper_cfg,
            audio_path=audio_path,
            work_dir=work_dir,
            reference_text=reference_text,
        )
        result["audio"] = str(config["audio"])
        results.append(result)

        t = result["timing"]
        s = result["scores_raw"]
        after_vad = result.get("whisper_duration_after_vad_ms")
        wav_speech = result.get("wav_speech_ms")
        print(
            f"  preprocess={t['preprocess_s']:.1f}s  transcribe={t['transcribe_s']:.1f}s  "
            f"total={t['total_s']:.1f}s  WER={s['wer_percent']}%  CER={s['cer_percent']}%"
        )
        if wav_speech is not None:
            print(f"  wav_speech={wav_speech/60000:.2f} min", end="")
        if after_vad is not None:
            print(f"  whisper_after_vad={after_vad/60000:.2f} min", end="")
        print()

        out_json = output_dir / f"{variant_id}.json"
        out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "timestamp": timestamp,
        "config": str(config_path.relative_to(ROOT)),
        "audio": config["audio"],
        "reference": config["reference"],
        "variants": results,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path = output_dir / "comparison.md"
    _write_markdown(md_path, config_path=config_path, results=results, reference_path=reference_path)

    print(f"\nWrote {summary_path.relative_to(ROOT)}")
    print(f"Wrote {md_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
