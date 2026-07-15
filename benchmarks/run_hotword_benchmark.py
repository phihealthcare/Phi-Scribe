#!/usr/bin/env python3
"""Benchmark hotword initial_prompt vs all-stacks baseline (Whisper raw, no postprocess)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from benchmarks.run_stack_benchmark import _run_stack
from benchmarks.stack_config import merge_stack_env

load_dotenv()

STACK_ID = "spectral_hpf_agc_loudness_vad"
OLD_PROMPT = (
    "Transcrição literal de anamnese em português brasileiro. "
    "Diálogo entre médica interna e paciente. Preservar a fala original."
)
HOTWORDS_PROMPT_PATH = ROOT / "benchmarks" / "prompts" / "whisper-initial-hotwords.txt"
BASELINE_DIR = ROOT / "benchmarks" / "results"
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


def _whisper_cfg(initial_prompt: str) -> dict:
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
        "word_count_hypothesis": scores.get("word_count_hypothesis"),
        "source": str(path.relative_to(ROOT)),
    }


def _write_summary(path: Path, rows: list[dict]) -> None:
    lines = [
        "# Hotword initial_prompt benchmark",
        "",
        f"Stack: `{STACK_ID}` · Whisper raw · sem postprocess",
        "",
        "| Áudio | Baseline WER | Baseline CER | Hotwords WER | Hotwords CER | Δ WER | Δ CER |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        base_wer = row.get("baseline_wer")
        base_cer = row.get("baseline_cer")
        delta_wer = row.get("delta_wer_pp")
        delta_cer = row.get("delta_cer_pp")
        delta_wer_s = f"{delta_wer:+.2f}" if delta_wer is not None else "—"
        delta_cer_s = f"{delta_cer:+.2f}" if delta_cer is not None else "—"
        lines.append(
            f"| {row['audio']} | {base_wer if base_wer is not None else '—'} "
            f"| {base_cer if base_cer is not None else '—'} "
            f"| {row['hotwords_wer']} | {row['hotwords_cer']} "
            f"| {delta_wer_s} | {delta_cer_s} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if not HOTWORDS_PROMPT_PATH.is_file():
        print(f"Missing {HOTWORDS_PROMPT_PATH}", file=sys.stderr)
        return 1

    hotwords_prompt = HOTWORDS_PROMPT_PATH.read_text(encoding="utf-8").strip()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = BASELINE_DIR / "hotword-prompt" / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    postprocess_options = {"enabled": False}
    rows: list[dict] = []

    from benchmarks.score import load_reference_text

    for index in range(1, 5):
        audio_stem = f"anamnesia-{index}"
        audio_path = ROOT / "public" / f"{audio_stem}.mp3"
        reference_path = ROOT / "benchmarks" / "references" / f"{audio_stem}.txt"
        if not audio_path.is_file() or not reference_path.is_file():
            print(f"Skip {audio_stem}: missing audio or reference", file=sys.stderr)
            continue

        print(f"Running {audio_stem} with hotword prompt ...", flush=True)
        result = _run_stack(
            stack_id=STACK_ID,
            stack_env=STACK_ENV,
            audio_path=audio_path,
            work_dir=output_dir / "wav" / audio_stem,
            whisper_cfg=_whisper_cfg(hotwords_prompt),
            reference_text=load_reference_text(reference_path),
            remove_fillers=False,
            postprocess_options=postprocess_options,
        )
        out_path = output_dir / f"{audio_stem}.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        baseline = _baseline_scores(audio_stem)
        hot_wer = result["scores"]["wer_percent"]
        hot_cer = result["scores"]["cer_percent"]
        row = {
            "audio": audio_stem,
            "hotwords_wer": hot_wer,
            "hotwords_cer": hot_cer,
            "hotwords_words": result["scores"]["word_count_hypothesis"],
            "baseline_wer": baseline["wer_percent"] if baseline else None,
            "baseline_cer": baseline["cer_percent"] if baseline else None,
            "baseline_source": baseline["source"] if baseline else None,
            "delta_wer_pp": round(hot_wer - baseline["wer_percent"], 2) if baseline else None,
            "delta_cer_pp": round(hot_cer - baseline["cer_percent"], 2) if baseline else None,
            "old_prompt": OLD_PROMPT,
            "new_prompt": hotwords_prompt,
        }
        rows.append(row)
        delta = f"{row['delta_wer_pp']:+.2f} pp" if row["delta_wer_pp"] is not None else "n/a"
        print(
            f"  WER={hot_wer}% CER={hot_cer}% (baseline WER={row['baseline_wer']}%, Δ {delta})",
            flush=True,
        )

    summary = {"timestamp": timestamp, "stack_id": STACK_ID, "results": rows}
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_summary(output_dir / "summary.md", rows)
    print(f"\nWrote {output_dir.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
