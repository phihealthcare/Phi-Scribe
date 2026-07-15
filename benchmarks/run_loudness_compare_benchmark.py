#!/usr/bin/env python3
"""Compare original ffmpeg loudnorm vs lufs_fast (time + WER/CER)."""

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


def _step_duration(timing: dict, name: str) -> float | None:
    for step in timing.get("steps", []):
        if (step.get("name") or step.get("step")) == name:
            return step.get("duration_s")
    return None


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

    t_transcribe = time.perf_counter()
    transcription = transcribe_wav(output_wav, **transcribe_options_from_mapping(whisper_cfg))
    transcribe_s = time.perf_counter() - t_transcribe

    scores = score_transcript(reference_text, str(transcription.get("text", "")))
    loudness_meta = processed.get("loudness")

    return {
        "variant_id": variant_id,
        "description": description,
        "stack_env": stack_env,
        "whisper": {k: v for k, v in whisper_cfg.items() if k != "initial_prompt"},
        "stages": processed.get("stages", []),
        "loudness": loudness_meta,
        "timing": {
            "preprocess_s": round(preprocess_s, 3),
            "loudness_s": _step_duration(timing, "loudness"),
            "vad_s": _step_duration(timing, "vad"),
            "transcribe_s": round(transcribe_s, 3),
            "total_s": round(preprocess_s + transcribe_s, 3),
            "upload_timing": timing,
        },
        "audio_duration_ms": processed.get("wav", {}).get("duration_ms"),
        "duration_after_vad_ms": transcription.get("duration_after_vad_ms"),
        "scores_raw": scores,
        "text_preview": str(transcription.get("text", ""))[:400],
    }


def _write_markdown(path: Path, *, results: list[dict], audio: str, reference: str) -> None:
    lines = [
        "# Loudness comparison — consulta-real-1",
        "",
        f"- **Audio:** `{audio}`",
        f"- **Reference:** `{reference}`",
        "- **Stack:** spectral_hpf_agc_loudness_vad (only `LOUDNESS_MODE` changes)",
        "",
        "## Summary",
        "",
        "| Variant | Mode | Loudness (s) | Preprocess (s) | Transcribe (s) | Total (s) | WER | CER |",
        "|---------|------|--------------|----------------|----------------|-----------|-----|-----|",
    ]
    for row in results:
        t = row["timing"]
        s = row["scores_raw"]
        mode = (row.get("loudness") or {}).get("mode") or row["stack_env"].get("LOUDNESS_MODE")
        lines.append(
            f"| `{row['variant_id']}` | `{mode}` | {t.get('loudness_s')} "
            f"| {t['preprocess_s']} | {t['transcribe_s']} | {t['total_s']} "
            f"| {s['wer_percent']}% | {s['cer_percent']}% |"
        )

    if len(results) >= 2:
        base, fast = results[0], results[1]
        d_loud = None
        if base["timing"].get("loudness_s") is not None and fast["timing"].get("loudness_s") is not None:
            d_loud = round(fast["timing"]["loudness_s"] - base["timing"]["loudness_s"], 3)
        d_wer = round(fast["scores_raw"]["wer_percent"] - base["scores_raw"]["wer_percent"], 2)
        d_cer = round(fast["scores_raw"]["cer_percent"] - base["scores_raw"]["cer_percent"], 2)
        d_total = round(fast["timing"]["total_s"] - base["timing"]["total_s"], 2)
        ok_wer = d_wer <= 0.10
        ok_cer = d_cer <= 0.10
        lines.extend(
            [
                "",
                f"### `{fast['variant_id']}` vs `{base['variant_id']}`",
                "",
                f"- Δ loudness step: **{d_loud:+}s**" if d_loud is not None else "- Δ loudness step: —",
                f"- Δ total time: **{d_total:+.2f}s**",
                f"- Δ WER: **{d_wer:+.2f} pp** {'✅' if ok_wer else '❌'} (gate ≤ +0.10 pp)",
                f"- Δ CER: **{d_cer:+.2f} pp** {'✅' if ok_cer else '❌'} (gate ≤ +0.10 pp)",
            ]
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare loudness lufs vs lufs_fast.")
    parser.add_argument("--config", default="benchmarks/loudness_compare_consulta-real-1.yaml")
    parser.add_argument("--only", help="Comma-separated variant ids")
    parser.add_argument("--output", help="Output directory")
    args = parser.parse_args()

    config_path = (ROOT / args.config).resolve()
    config = _load_config(config_path)
    audio_path = (ROOT / config["audio"]).resolve()
    reference_path = (ROOT / config["reference"]).resolve()
    if not audio_path.is_file() or not reference_path.is_file():
        print("Audio or reference missing.", file=sys.stderr)
        return 1

    reference_text = load_reference_text(reference_path)
    whisper_cfg = resolve_whisper_block(config["whisper"])
    base_stack = merge_stack_env(config.get("base_stack") or {})
    variants: dict = config["variants"]
    selected = list(variants.keys())
    if args.only:
        selected = [item.strip() for item in args.only.split(",") if item.strip()]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        Path(args.output).resolve()
        if args.output
        else ROOT / "benchmarks/results/loudness-compare-consulta-real-1" / timestamp
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir = output_dir / "wav"
    work_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for variant_id in selected:
        variant = variants[variant_id]
        stack_env = {**base_stack, **(variant.get("stack_overrides") or {})}
        print(f"\n=== {variant_id}: {variant.get('description', '')} ===")
        print(f"  LOUDNESS_MODE={stack_env.get('LOUDNESS_MODE')}")
        result = _run_variant(
            variant_id=variant_id,
            description=str(variant.get("description", "")),
            stack_env=stack_env,
            whisper_cfg=whisper_cfg,
            audio_path=audio_path,
            work_dir=work_dir,
            reference_text=reference_text,
        )
        results.append(result)
        t, s = result["timing"], result["scores_raw"]
        print(
            f"  loudness={t.get('loudness_s')}s  preprocess={t['preprocess_s']:.1f}s  "
            f"transcribe={t['transcribe_s']:.1f}s  total={t['total_s']:.1f}s  "
            f"WER={s['wer_percent']}%  CER={s['cer_percent']}%"
        )
        (output_dir / f"{variant_id}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    summary = {
        "timestamp": timestamp,
        "config": str(config_path.relative_to(ROOT)),
        "audio": config["audio"],
        "reference": config["reference"],
        "variants": results,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_markdown(
        output_dir / "comparison.md",
        results=results,
        audio=config["audio"],
        reference=config["reference"],
    )
    print(f"\nWrote {output_dir.relative_to(ROOT)}/summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
