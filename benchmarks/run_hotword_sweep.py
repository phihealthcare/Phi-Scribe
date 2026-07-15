#!/usr/bin/env python3
"""Sweep Whisper initial_prompt hotword variants (WER/CER on anamnesia 1–4)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from app.services.audio_processor import preprocess_audio
from app.services.transcribe import transcribe_options_from_mapping, transcribe_wav
from benchmarks.build_initial_prompt import prompt_variants
from benchmarks.score import load_reference_text, score_transcript
from benchmarks.stack_config import merge_stack_env, stack_env_to_preprocess_kwargs

load_dotenv()

STACK_ID = "spectral_hpf_agc_loudness_vad"
BASELINE_DIR = ROOT / "benchmarks" / "results"
RELIABLE_AUDIOS = ("anamnesia-3", "anamnesia-4")

STACK_ENV = merge_stack_env(
    {
        "DENOISE_ENABLED": True,
        "DENOISE_PROP_DECREASE": 0.6,
        "HPF_ENABLED": True,
        "HPF_CUTOFF_HZ": 80.0,
        "AGC_ENABLED": True,
        "AGC_TARGET_DBFS": -20.0,
        "AGC_MAX_GAIN_DB": 12.0,
        "AGC_WINDOW_MS": 30,
        "LOUDNESS_ENABLED": True,
        "LOUDNESS_MODE": "lufs",
        "LOUDNESS_TARGET_LUFS": -23.0,
        "LOUDNESS_TRUE_PEAK": -1.5,
        "LOUDNESS_LRA": 11.0,
        "VAD_ENABLED": True,
        "VAD_THRESHOLD": 0.35,
        "VAD_MIN_SPEECH_DURATION_MS": 100,
        "VAD_MIN_SILENCE_DURATION_MS": 2500,
        "VAD_SPEECH_PAD_MS": 600,
        "LPF_ENABLED": False,
    }
)


def _whisper_mapping(initial_prompt: str) -> dict:
    return {
        "model": "large-v3",
        "device": "cuda",
        "compute_type": "int8_float16",
        "language": "pt",
        "beam_size": 5,
        "initial_prompt": initial_prompt,
        "compression_ratio_threshold": 1.8,
        "log_prob_threshold": -0.8,
        "hallucination_silence_threshold": 1.0,
        "condition_on_previous_text": False,
        "vad_filter": False,
        "chunking_enabled": False,
    }


def _baseline_scores(audio_stem: str) -> dict | None:
    path = BASELINE_DIR / audio_stem / "all-stacks" / f"{STACK_ID}.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    scores = payload.get("scores_raw") or payload.get("scores")
    if not scores:
        return None
    return {
        "wer_percent": scores["wer_percent"],
        "cer_percent": scores["cer_percent"],
    }


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _write_summary(path: Path, rows: list[dict]) -> None:
    ranked = sorted(rows, key=lambda row: (row["mean_wer_an34"], row["mean_wer_all"]))
    lines = [
        "# Hotword prompt sweep",
        "",
        "Stack `spectral_hpf_agc_loudness_vad` · Whisper raw · sem postprocess.",
        "Ranking: média WER em anamnesia-3/4 (referências mais confiáveis), depois média nos 4.",
        "",
        "| Rank | Variant | Terms | WER an-3/4 | CER an-3/4 | WER all-4 | CER all-4 | Δ WER an-3/4 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for index, row in enumerate(ranked, start=1):
        lines.append(
            f"| {index} | `{row['label']}` | {row['term_count']} "
            f"| {row['mean_wer_an34']} | {row['mean_cer_an34']} "
            f"| {row['mean_wer_all']} | {row['mean_cer_all']} "
            f"| {row['delta_wer_an34_pp']:+.2f} |"
        )
    lines.extend(["", "## Per audio", ""])
    for row in ranked[:3]:
        lines.append(f"### `{row['label']}` ({row['term_count']} terms)")
        lines.append("")
        lines.append("| Áudio | WER | CER | Δ WER vs baseline |")
        lines.append("| --- | ---: | ---: | ---: |")
        for audio_row in row["per_audio"]:
            lines.append(
                f"| {audio_row['audio']} | {audio_row['wer_percent']} | {audio_row['cer_percent']} "
                f"| {audio_row['delta_wer_pp']:+.2f} |"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = BASELINE_DIR / "hotword-sweep" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    variants = prompt_variants()
    (output_dir / "variants.json").write_text(
        json.dumps(
            [
                {k: v for k, v in variant.items() if k != "hotwords"}
                for variant in variants
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    audio_jobs: list[dict] = []
    for index in range(1, 5):
        audio_stem = f"anamnesia-{index}"
        audio_path = ROOT / "public" / f"{audio_stem}.mp3"
        reference_path = ROOT / "benchmarks" / "references" / f"{audio_stem}.txt"
        if not audio_path.is_file() or not reference_path.is_file():
            print(f"Skip {audio_stem}: missing files", file=sys.stderr)
            continue
        wav_path = output_dir / "wav" / f"{audio_stem}.wav"
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Preprocessing {audio_stem} ...", flush=True)
        preprocess_audio(
            audio_path,
            wav_path,
            **stack_env_to_preprocess_kwargs(STACK_ENV),
        )
        audio_jobs.append(
            {
                "audio": audio_stem,
                "wav_path": wav_path,
                "reference_text": load_reference_text(reference_path),
                "baseline": _baseline_scores(audio_stem),
            }
        )

    summary_rows: list[dict] = []
    total_variants = len(variants)

    for variant_index, variant in enumerate(variants, start=1):
        label = variant["label"]
        print(f"\n[{variant_index}/{total_variants}] {label} ({variant['term_count']} terms)", flush=True)
        per_audio: list[dict] = []

        for job in audio_jobs:
            transcribe_options = transcribe_options_from_mapping(_whisper_mapping(variant["prompt"]))
            transcription = transcribe_wav(job["wav_path"], **transcribe_options)
            scores = score_transcript(job["reference_text"], transcription["text"])
            baseline = job["baseline"]
            delta_wer = (
                round(scores["wer_percent"] - baseline["wer_percent"], 2) if baseline else None
            )
            per_audio.append(
                {
                    "audio": job["audio"],
                    "wer_percent": scores["wer_percent"],
                    "cer_percent": scores["cer_percent"],
                    "word_count_hypothesis": scores["word_count_hypothesis"],
                    "baseline_wer": baseline["wer_percent"] if baseline else None,
                    "baseline_cer": baseline["cer_percent"] if baseline else None,
                    "delta_wer_pp": delta_wer,
                    "delta_cer_pp": (
                        round(scores["cer_percent"] - baseline["cer_percent"], 2) if baseline else None
                    ),
                }
            )
            print(
                f"  {job['audio']}: WER={scores['wer_percent']}% CER={scores['cer_percent']}% "
                f"(Δ WER {delta_wer:+.2f} pp)" if delta_wer is not None else f"  {job['audio']}: WER={scores['wer_percent']}%",
                flush=True,
            )

        an34 = [row for row in per_audio if row["audio"] in RELIABLE_AUDIOS]
        all_wer = [row["wer_percent"] for row in per_audio]
        all_cer = [row["cer_percent"] for row in per_audio]
        an34_wer = [row["wer_percent"] for row in an34]
        an34_cer = [row["cer_percent"] for row in an34]
        an34_delta = [row["delta_wer_pp"] for row in an34 if row["delta_wer_pp"] is not None]

        summary_rows.append(
            {
                "label": label,
                "term_count": variant["term_count"],
                "strategy": variant["strategy"],
                "compact": variant["compact"],
                "prompt_chars": len(variant["prompt"]),
                "mean_wer_an34": _mean(an34_wer),
                "mean_cer_an34": _mean(an34_cer),
                "mean_wer_all": _mean(all_wer),
                "mean_cer_all": _mean(all_cer),
                "delta_wer_an34_pp": _mean(an34_delta),
                "per_audio": per_audio,
                "prompt": variant["prompt"],
            }
        )

        variant_path = output_dir / f"{label}.json"
        variant_path.write_text(
            json.dumps(summary_rows[-1], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    (output_dir / "summary.json").write_text(
        json.dumps(summary_rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_summary(output_dir / "summary.md", summary_rows)

    best = min(summary_rows, key=lambda row: (row["mean_wer_an34"], row["mean_wer_all"]))
    print(
        f"\nBest (an-3/4 mean WER): {best['label']} — "
        f"WER an-3/4={best['mean_wer_an34']}% (Δ {best['delta_wer_an34_pp']:+.2f} pp vs baseline)"
    )
    print(f"Wrote {output_dir.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
