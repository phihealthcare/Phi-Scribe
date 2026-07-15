#!/usr/bin/env python3
"""Run full transcribe flow on one stack and score WER/CER at each stage."""
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

load_dotenv()

from app.config import Config
from app.services.audio_processor import preprocess_audio
from app.services.pipeline_steps import (
    TRANSCRIBE_04_LLM_ASR_FIX,
    TRANSCRIBE_04B_LLM_DIARIZATION_LABELS,
    UPLOAD_01_INPUT,
)
from app.services.pipeline_steps import omitted_pipeline_steps_for_config
from app.services.pipeline_tracker import PipelineTracker
from app.services.soap_draft import generate_soap_draft_from_config, skip_soap_pipeline_steps
from app.services.soap_prerequisites import can_generate_soap, soap_draft_skipped_result
from app.services.transcribe import transcribe_options_from_mapping, transcribe_wav
from app.services.transcribe_diarized import diarization_options_from_mapping, transcribe_wav_diarized
from app.services.transcript_postprocess import (
    diarization_labels_applied,
    edit_transcript_from_config,
    save_postprocess_diff_file,
)
from benchmarks.score import load_reference_text, score_transcript
from benchmarks.stack_config import merge_stack_env, resolve_whisper_block, stack_env_to_preprocess_kwargs


def _score(label: str, reference: str, hypothesis: str) -> dict:
    scores = score_transcript(reference, hypothesis)
    print(
        f"  {label:24} WER={scores['wer_percent']:6.2f}% "
        f"CER={scores['cer_percent']:6.2f}% words={scores['word_count_hypothesis']}"
    )
    return scores


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run anamnesia-3 full pipeline with LLM logging.")
    parser.add_argument(
        "--no-diarization",
        action="store_true",
        help="Skip pyannote (faster; matches historical WER benchmark methodology)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory (default: benchmarks/results/anamnesia-3/flow-test-<timestamp>)",
    )
    parser.add_argument(
        "--no-soap",
        action="store_true",
        help="Skip SOAP draft generation (Whisper + LLM postprocess only)",
    )
    args = parser.parse_args()

    stacks_path = ROOT / "benchmarks/stacks_anamnesia-3-best.yaml"
    config = yaml.safe_load(stacks_path.read_text(encoding="utf-8"))
    stack_id = "spectral_lpf_agc"
    stack_env = merge_stack_env(config["stacks"][stack_id])

    audio_path = (ROOT / config["audio"]).resolve()
    reference_path = (ROOT / config["reference"]).resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output) if args.output else ROOT / f"benchmarks/results/anamnesia-3/flow-test-{timestamp}"
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    work_wav = output_dir / f"{stack_id}.wav"
    pipeline_log_dir = output_dir / "pipeline"
    app_config = {key: getattr(Config, key) for key in dir(Config) if key.isupper()}
    tracker = None
    if app_config.get("PIPELINE_DEBUG_LOG_ENABLED"):
        tracker = PipelineTracker(
            run_id=f"flow-test-{timestamp}",
            log_dir=pipeline_log_dir,
            omitted_step_ids=omitted_pipeline_steps_for_config(app_config),
        )

    reference = load_reference_text(reference_path)
    whisper_cfg = resolve_whisper_block(config["whisper"])
    diarization_enabled = bool(app_config.get("DIARIZATION_ENABLED")) and not args.no_diarization

    print(f"Audio: {audio_path.name}")
    print(f"Stack: {stack_id} (best historical WER ~16.61%)")
    print(f"Diarization: {diarization_enabled}")
    print(f"Postprocess: {app_config.get('TRANSCRIPT_POSTPROCESS_ENABLED')}")
    print(f"Output: {output_dir.relative_to(ROOT)}")
    if tracker:
        print(f"Pipeline log: {pipeline_log_dir.relative_to(ROOT)}")
    print()

    t0 = time.perf_counter()
    print("1) Preprocess...")
    if tracker:
        tracker.record(
            UPLOAD_01_INPUT,
            request={"audio_path": str(audio_path), "stack_id": stack_id},
            response={"work_wav": str(work_wav)},
        )
    processed = preprocess_audio(
        audio_path,
        work_wav,
        **stack_env_to_preprocess_kwargs(stack_env),
        tracker=tracker,
    )
    stages = processed.get("stages", [])
    print(f"   stages={stages} ({time.perf_counter() - t0:.1f}s)")

    t1 = time.perf_counter()
    print("2) Transcribe (Whisper)...")
    transcribe_kwargs = transcribe_options_from_mapping(whisper_cfg)
    diarization_opts = diarization_options_from_mapping(app_config)
    if diarization_enabled:
        transcription = transcribe_wav_diarized(
            work_wav,
            transcribe_options=transcribe_kwargs,
            diarization_options=diarization_opts,
            tracker=tracker,
        )
    else:
        if tracker:
            from app.services.pipeline_steps import (
                TRANSCRIBE_01_DIARIZATION,
                TRANSCRIBE_02_WHISPER,
                TRANSCRIBE_03_FORMAT_SPEAKERS,
            )

            tracker.skip(TRANSCRIBE_01_DIARIZATION, reason="diarization_disabled")
        t_whisper = time.perf_counter()
        transcription = transcribe_wav(work_wav, **transcribe_kwargs)
        if tracker:
            tracker.record(
                TRANSCRIBE_02_WHISPER,
                request={"wav_path": str(work_wav), **transcribe_kwargs},
                response={
                    "text": transcription.get("text"),
                    "duration_ms": transcription.get("duration_ms"),
                    "run": transcription.get("run"),
                },
                duration_ms=(time.perf_counter() - t_whisper) * 1000,
            )
            tracker.skip(TRANSCRIBE_03_FORMAT_SPEAKERS, reason="diarization_disabled")
    raw_text = str(transcription.get("text", ""))
    _write_text(output_dir / "01_whisper_raw.txt", raw_text)
    print(f"   done ({time.perf_counter() - t1:.1f}s, {len(raw_text.split())} words)")

    print("\nScores vs reference:")
    scores_whisper = _score("Whisper raw", reference, raw_text)

    t2 = time.perf_counter()
    print("\n3) LLM postprocess (Gemma)...")
    postprocess_result = edit_transcript_from_config(
        raw_text,
        app_config,
        preprocessing_stages=stages,
        diarization_enabled=diarization_enabled,
        tracker=tracker,
    )
    if postprocess_result["skipped"]:
        print(f"   SKIPPED: {postprocess_result['error']}")
        postprocessed_text = raw_text
        scores_post = scores_whisper
    else:
        postprocessed_text = postprocess_result["text"]
        diff = postprocess_result.get("diff", {})
        asr_fix = postprocess_result.get("asr_fix") or {}
        diarization_labels = postprocess_result.get("diarization_labels") or {}
        print(
            f"   ok ({time.perf_counter() - t2:.1f}s, "
            f"changes={diff.get('change_count', 0)}, "
            f"asr_fix={'ok' if not asr_fix.get('skipped') else 'skip'}, "
            f"labels={'ok' if not diarization_labels.get('skipped') else 'skip'})"
        )
        _write_text(output_dir / "02_postprocess_text.txt", postprocessed_text)
        if tracker:
            if not asr_fix.get("skipped") and asr_fix.get("diff"):
                tracker.amend(TRANSCRIBE_04_LLM_ASR_FIX, response={"diff": asr_fix["diff"]})
            if not diarization_labels.get("skipped") and diarization_labels.get("diff"):
                tracker.amend(
                    TRANSCRIBE_04B_LLM_DIARIZATION_LABELS,
                    response={"diff": diarization_labels["diff"]},
                )
        save_postprocess_diff_file(
            output_dir / "postprocess.diff.txt",
            raw_text=raw_text,
            corrected_text=postprocessed_text,
            diff=diff,
            meta={
                "stack_id": stack_id,
                "model": postprocess_result.get("model"),
                "provider": postprocess_result.get("provider"),
            },
            label=stack_id,
        )
        scores_post = _score("After postprocess", reference, postprocessed_text)

    t3 = time.perf_counter()
    soap_result: dict = {"skipped": True, "error": "disabled_by_flag"}
    if args.no_soap:
        print("\n4) SOAP draft — skipped (--no-soap)")
        if tracker:
            split_enabled = bool(app_config.get("SOAP_SPLIT_ENABLED", True))
            skip_soap_pipeline_steps(
                tracker,
                reason="flow_test_no_soap",
                split_enabled=split_enabled,
            )
    else:
        print("\n4) SOAP draft (Gemma JSON)...")
        soap_ok, soap_skip_reason = can_generate_soap(
            postprocess_result,
            diarization_enabled=diarization_enabled,
        )
        if soap_ok:
            soap_result = generate_soap_draft_from_config(
                postprocessed_text,
                app_config,
                segments=transcription.get("segments") if isinstance(transcription.get("segments"), list) else None,
                diarization_enabled=diarization_enabled,
                postprocess_applied=diarization_labels_applied(postprocess_result),
                tracker=tracker,
            )
        else:
            if tracker:
                split_enabled = bool(app_config.get("SOAP_SPLIT_ENABLED", True))
                skip_soap_pipeline_steps(
                    tracker,
                    reason=soap_skip_reason,
                    split_enabled=split_enabled,
                )
            soap_result = soap_draft_skipped_result(
                config=app_config,
                segmented_transcript=postprocessed_text,
                diarization_enabled=diarization_enabled,
                postprocess_applied=diarization_labels_applied(postprocess_result),
                error=soap_skip_reason,
            )
        if soap_result["skipped"]:
            print(f"   SKIPPED: {soap_result['error']}")
        else:
            doc = soap_result.get("document") or {}
            print(f"   ok ({time.perf_counter() - t3:.1f}s, keys={list(doc.keys()) if isinstance(doc, dict) else 0})")
            if isinstance(doc, dict):
                _write_text(
                    output_dir / "03_soap_document.json",
                    json.dumps(doc, ensure_ascii=False, indent=2),
                )

    delta_wer = scores_post["wer_percent"] - scores_whisper["wer_percent"]
    delta_cer = scores_post["cer_percent"] - scores_whisper["cer_percent"]

    report = {
        "stack_id": stack_id,
        "historical_best_wer_percent": 16.61,
        "stages": stages,
        "diarization_enabled": diarization_enabled,
        "scores_whisper": scores_whisper,
        "scores_postprocess": scores_post,
        "delta_wer_percent": round(delta_wer, 2),
        "delta_cer_percent": round(delta_cer, 2),
        "postprocess": {
            "skipped": postprocess_result["skipped"],
            "error": postprocess_result["error"],
            "model": postprocess_result.get("model"),
            "change_count": (postprocess_result.get("diff") or {}).get("change_count"),
            "pipeline_step_asr_fix": "transcribe_04_llm_asr_fix",
            "pipeline_step_diarization_labels": "transcribe_04b_llm_diarization_labels",
        },
        "soap_draft": {
            "skipped": soap_result["skipped"],
            "error": soap_result["error"],
            "has_document": soap_result.get("document") is not None,
            "pipeline_steps": [
                "transcribe_05a_llm_soap_subjetivo",
                "transcribe_05b_llm_soap_objetivo",
                "transcribe_05c_llm_soap_avaliacao",
                "transcribe_05d_llm_soap_plano",
            ],
        },
        "pipeline_log": {
            "enabled": tracker is not None,
            "log_dir": str(pipeline_log_dir) if tracker else None,
            "manifest": str(pipeline_log_dir / "manifest.json") if tracker else None,
        },
        "artifacts": {
            "whisper_text": str(output_dir / "01_whisper_raw.txt"),
            "postprocess_text": str(output_dir / "02_postprocess_text.txt"),
            "soap_document": str(output_dir / "03_soap_document.json"),
            "postprocess_diff": str(output_dir / "postprocess.diff.txt"),
        },
    }
    if soap_result.get("document"):
        report["soap_draft"]["document_keys"] = list(soap_result["document"].keys())

    out_path = output_dir / "flow_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"Whisper  → WER {scores_whisper['wer_percent']:.2f}%  CER {scores_whisper['cer_percent']:.2f}%")
    print(f"Postproc → WER {scores_post['wer_percent']:.2f}%  CER {scores_post['cer_percent']:.2f}%")
    print(f"Delta    → WER {delta_wer:+.2f}pp  CER {delta_cer:+.2f}pp")
    print(f"(Historical best stack WER: 16.61% — whisper-only, no diarization)")
    print(f"Report:   {out_path.relative_to(ROOT)}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
