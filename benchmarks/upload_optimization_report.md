# Upload preprocess optimization report

Stack: **`spectral_hpf_agc_loudness_vad`** (unchanged — same algorithms and `.env` parameters).

## Baseline (before optimizations)

Source: `uploads/processed/49dcc418-bdd2-47d2-a730-a45b11e45c8e.pipeline/upload_timing.json`

| step | duration_s |
|------|------------|
| save_file | 0.005 |
| normalize | 0.395 |
| band_filters | 0.395 |
| denoise | 4.105 |
| agc | **9.563** |
| loudness | **16.217** |
| vad | **11.235** |
| export_pcm | 0.081 |
| **TOTAL** | **~42.0** |

## Optimizations applied

| Change | File(s) | Expected impact |
|--------|---------|-----------------|
| AGC `_smooth_gain` via **numba** | `app/services/agc.py` | agc ~9.5s → sub-second |
| Loudness **single ffmpeg** (`loudnorm` + `print_format=summary`) | `app/services/loudness.py` | loudness ~16s → ~5–8s |
| **In-memory** HPF → denoise → AGC (one disk write) | `app/services/audio_processor.py` | fewer I/O passes |
| **`EXPORT_PCM_ENABLED=false`** default (opt-in) | `app/config.py` | −export_pcm step |
| Upload timing benchmark | `benchmarks/run_upload_timing_benchmark.py` | measure per step |

## After optimizations (measured)

Same audio: `uploads/49dcc418-bdd2-47d2-a730-a45b11e45c8e.mp4` (~13.6 min)

Run: `benchmarks/results/upload-opt-optimized/20260710T192850Z/upload_timing_summary.json`

| step | before (s) | after (s) | delta |
|------|------------|-----------|-------|
| normalize | 0.395 | 0.391 | ~same |
| band_filters | 0.395 | 0.308 | −22% |
| denoise | 4.105 | 4.068 | ~same |
| agc | **9.563** | **0.323** | **−97%** |
| loudness | **16.217** | **13.204** | −19% |
| vad | 11.235 | 11.245 | ~same |
| export_pcm | 0.081 | *(disabled)* | −100% |
| **TOTAL** | **~42.0** | **~29.6** | **−30%** |

Notes:
- AGC numba hit the ≤1s target.
- Loudness improved but still above 8s — ffmpeg `loudnorm` on ~13 min audio dominates.
- VAD remains CPU-bound (~11s); GPU Silero is a future P2 item.
- WER/CER gate: run `run_stack_benchmark.py` on anamnesia-1..4 before merging to production.

## WER/CER gate (fill in)

Baseline WER reference: **8.92%** average (`benchmarks/benchmark_analysis.md`).

```bash
# Same audio + reference as stack benchmark
python benchmarks/run_stack_benchmark.py \
  --stacks benchmarks/stacks.yaml \
  --only spectral_hpf_agc_loudness_vad \
  --output benchmarks/results/upload-opt-optimized/wer

python benchmarks/score_transcripts.py \
  --reference benchmarks/references/anamnesia-1.txt \
  --hypothesis "benchmarks/results/upload-opt-optimized/wer/**/spectral_hpf_agc_loudness_vad.json" \
  --output benchmarks/results/upload-opt-optimized/wer/scores
```

Acceptance: per-audio WER/CER regression **≤ +0.10 pp** vs baseline run.

| Audio | WER before | WER after | CER before | CER after | OK? |
|-------|------------|-----------|------------|-----------|-----|
| anamnesia-1 | | | | | |
| anamnesia-2 | | | | | |
| anamnesia-3 | | | | | |
| anamnesia-4 | | | | | |

## Tests

```bash
pytest tests/test_agc.py tests/test_preprocess_regression.py tests/test_upload_timing.py -q
```
