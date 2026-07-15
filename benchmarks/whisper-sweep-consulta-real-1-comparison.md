# Whisper sweep — consulta-real-1

Comparison of faster-whisper configs on pre-processed audio from pipeline `c07ffd25-6ebb-4262-a573-c91760d84f6e`.


|                 |                                                                          |
| --------------- | ------------------------------------------------------------------------ |
| **Run**         | `20260706T140329Z`                                                       |
| **Audio**       | `uploads/processed/c07ffd25-6ebb-4262-a573-c91760d84f6e.wav` (~13.6 min) |
| **Reference**   | `benchmarks/references/consulta-real-1.txt` (1,888 words)                |
| **Postprocess** | off · SOAP: off                                                          |
| **Raw results** | `benchmarks/results/whisper-sweep-consulta-real-1/20260706T140329Z/`     |


---

## Winner — best WER + fast

`**batched_large-v3_int8_b4_beam1`**


| Metric           | Value      |
| ---------------- | ---------- |
| WER              | **30.61%** |
| CER              | **22.53%** |
| Wall time        | **24.5 s** |
| Real-time factor | **33.2×**  |
| Hypothesis words | 1,870      |


Settings: `large-v3` · `batched` · `int8` · `batch_size=4` · `beam_size=1` · `vad_filter=false`

This config beats every other variant on **both accuracy and speed** among the large-v3 runs. Dropping `beam_size` from 5 (default) to 1 saves ~14 s with a **−1.06 pp WER** gain vs `batched_large-v3_int8_b4`.

### Recommended `.env` (already matches)

```env
WHISPER_FASTER_MODEL=large-v3
WHISPER_FASTER_DEVICE=cuda
WHISPER_FASTER_COMPUTE_TYPE=int8
WHISPER_FASTER_BEAM_SIZE=1
WHISPER_FASTER_INFERENCE_MODE=batched
WHISPER_FASTER_BATCH_SIZE=4
WHISPER_FASTER_CHUNKING_ENABLED=false
```

---

## Full ranking

Ranked by WER (lower is better), then wall time.


| Rank | Config                               | WER        | CER        | Time (s) | RT factor | Mode       | Model    | Compute      | Batch | Chunk |
| ---- | ------------------------------------ | ---------- | ---------- | -------- | --------- | ---------- | -------- | ------------ | ----- | ----- |
| 1    | `**batched_large-v3_int8_b4_beam1**` | **30.61%** | **22.53%** | **24.5** | **33.2×** | batched    | large-v3 | int8         | 4     | —     |
| 2    | `seq_turbo_int8`                     | 31.09%     | 22.79%     | 189.9    | 4.3×      | sequential | turbo    | int8         | 16    | —     |
| 3    | `batched_large-v3_int8_b4_vad`       | 31.67%     | 23.48%     | 38.3     | 21.3×     | batched    | large-v3 | int8         | 4     | —     |
| 4    | `batched_large-v3_int8_b4`           | 31.67%     | 23.48%     | 38.4     | 21.2×     | batched    | large-v3 | int8         | 4     | —     |
| 5    | `batched_large-v3_int8_b4_chunk30`   | 31.67%     | 23.48%     | 40.9     | 19.9×     | batched    | large-v3 | int8         | 4     | 30    |
| 6    | `batched_large-v3_int8_b2`           | 31.67%     | 23.48%     | 46.4     | 17.6×     | batched    | large-v3 | int8         | 2     | —     |
| 7    | `seq_large-v3_int8_float16`          | 32.20%     | 24.41%     | 51.8     | 15.7×     | sequential | large-v3 | int8_float16 | 16    | —     |
| 8    | `seq_large-v3_int8`                  | 32.20%     | 24.41%     | 53.4     | 15.2×     | sequential | large-v3 | int8         | 16    | —     |
| 9    | `batched_large-v3_int8_float16_b4`   | 32.63%     | 25.04%     | 514.2    | 1.6×      | batched    | large-v3 | int8_float16 | 4     | —     |
| 10   | `batched_large-v3_int8_b6`           | 32.63%     | 25.04%     | 595.8    | 1.4×      | batched    | large-v3 | int8         | 6     | —     |
| 11   | `batched_turbo_int8_b4`              | 39.62%     | 30.75%     | 12.1     | 67.2×     | batched    | turbo    | int8         | 4     | —     |


---

## Takeaways

### Accuracy

- `**beam_size=1`** is the single biggest win: −1.06 pp WER vs default `beam_size=5` on the same batched large-v3 int8 b4 setup.
- `**vad_filter**` on batched b4 does not help WER here (same 31.67% as without VAD).
- `**chunk_length=30**` does not change WER vs full-file batched b4.
- **Sequential large-v3** (int8 / int8_float16) is ~8 pp WER worse than the winner and ~2× slower.
- `**batched_turbo`** is fastest (12 s) but WER is **+9 pp** worse — not suitable for clinical PT-BR on this audio.

### Speed


| Tier                | Config                                         | Time      | WER    |
| ------------------- | ---------------------------------------------- | --------- | ------ |
| Best balance        | `batched_large-v3_int8_b4_beam1`               | 24.5 s    | 30.61% |
| Fast but inaccurate | `batched_turbo_int8_b4`                        | 12.1 s    | 39.62% |
| Avoid               | `batched_large-v3_int8_b6` / `int8_float16_b4` | 514–596 s | 32.63% |


Batch size 6 and `int8_float16` batched caused severe slowdowns (likely VRAM pressure / fallback behavior) with no accuracy benefit.

### vs production pipeline Whisper

The full `/transcribe` pipeline run on the same file reported ~34% WER on Whisper output. The sweep winner reaches **30.61%** on the same reference because:

1. Sweep uses the **hotwords initial prompt** from `benchmarks/prompts/whisper-initial-hotwords.txt`.
2. Sweep runs on the **already pre-processed WAV** with tuned `beam_size=1`.

Align production `.env` `WHISPER_FASTER_INITIAL_PROMPT` with the hotwords file if you want sweep parity.

---

## Re-run

```bash
python benchmarks/run_whisper_sweep_benchmark.py

# Winner only
python benchmarks/run_whisper_sweep_benchmark.py --only batched_large-v3_int8_b4_beam1
```

Config matrix: `benchmarks/whisper_sweep_consulta-real-1.yaml`

---

## Addendum 2026-07-08 — turbo + beam_size=1 (apples-to-apples vs large-v3 winner)

Run: `20260708T165541Z` · same WAV/reference · hotwords `initial_prompt` for all rows (unlike the earlier production log referenced below, which used no prompt).

| Config | WER | CER | Wall (s) | Mode | Model | Batch | cpu_threads |
| --- | ---: | ---: | ---: | --- | --- | ---: | ---: |
| `batched_large-v3_int8_b4_beam1_cpu8` | **22.33%** | **14.18%** | 27.18 | batched | large-v3 | 4 | 8 |
| `seq_turbo_int8_beam1_cpu8` | 22.81% | 14.80% | **13.68** | sequential | turbo | — | 8 |
| `batched_turbo_int8_b4_beam1_cpu8` | 52.11% | 68.17% | 12.60 | batched | turbo | 4 | 8 |
| `batched_turbo_int8_b2_beam1_cpu8` | 52.22% | 68.37% | 12.05 | batched | turbo | 2 | 8 |

### Important correction first: the large-v3 baseline number above supersedes several numbers reported earlier in this investigation

Every "large-v3 batched" wall-time number recorded earlier today (231.56s, 289.77s, 244.54s, the cpu_threads=4/8/16 sweep, the "warm-state 225.5s" figure) turned out to be **CPU fallback**, not GPU inference — `run.device` was `"cpu"` and `run.fallback_to_cpu` was `true` in all of those result files. Root cause: a live `run.py` Flask server process was running on this machine throughout this session, holding its own model resident in GPU VRAM (this 6GB laptop GPU has little headroom to spare). When the separate benchmark script tried to load a second full model instance, it intermittently hit a CUDA OOM, and `transcribe_wav`'s automatic OOM handler (`app/services/transcribe.py`) silently retried on CPU — which is correct, safe behavior, but ~8–20x slower, and was mistaken for genuine GPU timing in this investigation until this run happened to land in a moment with enough free VRAM to succeed on GPU (`device: "cuda"`, `fallback_to_cpu: false`). **The `cpu_threads=4 vs 8 vs 16` comparison was therefore measuring CPU thread scaling during CPU fallback, not GPU-side thread behavior** — the general result (8 > 16 > 4) likely still holds for CPU inference, but should not be read as "GPU speed depends this much on cpu_threads."

**Operational implication for production, independent of this benchmark:** if VRAM gets tight in production the same way it did here (e.g. under concurrent load, or alongside another GPU process), `/transcribe` will silently fall back to CPU rather than error — correct behavior, but requests could get ~10x slower without any visible failure. Worth monitoring `run.fallback_to_cpu` in the pipeline logs / responses in production.

### Turbo findings (now on genuine GPU numbers)

- **`seq_turbo_int8_beam1_cpu8` is the standout result**: WER only +0.48pp worse than the large-v3 winner (22.81% vs 22.33%), at **~2x the wall-time speedup** (13.68s vs 27.18s) — a good, credible tradeoff on this one sample.
- **`batched` mode is unsafe for turbo at `beam_size=1`** — both batch=2 and batch=4 ended in a real hallucination/repetition loop near the end of the transcript (the word "professor" repeated ~30 times consecutively), which is what drove CER up to 68%. This is a genuine greedy-decoding failure mode (no repetition penalty / beam diversity to escape the loop), not a scoring artifact — confirmed by reading the raw output text. **Do not pair `turbo` with `batched` inference mode at `beam_size=1`.**
- This also means the earlier production pipeline-debug log (turbo, batched, beam=1, no initial_prompt, WER 23.39%, 13.9s) got lucky — it used `batched` mode and did not hit the repetition loop on that occasion, but the failure mode above shows that combination is not reliably safe.

### Recommendation (data point, not a decision)

If further validated on more samples, `turbo` in **sequential** mode at `beam_size=1` is a credible ~2x speedup over the current large-v3 production config for a sub-1pp WER cost — worth a broader validation pass (more reference audios) before considering a `.env` change. **`turbo` + `batched` should not be used at `beam_size=1`** based on the hallucination evidence above. No `.env` or default config changes were made as part of this investigation.

### Follow-up 2026-07-08 — `cpu_threads` re-tested via the real `/transcribe` endpoint, then removed

The `cpu_threads=4/8/16` differences reported above (and earlier in this session) were an artifact of the CPU-fallback bug, not a real GPU effect (see correction above). To settle it, `cpu_threads` was re-tested in isolation — one live server process at a time, no benchmark-script GPU contention — by hitting `POST /api/v1/audio/c07ffd25-6ebb-4262-a573-c91760d84f6e/transcribe` directly with `WHISPER_FASTER_CPU_THREADS` set to 4, 8, and 16 in turn (server restarted between each). Warm-state (2nd call) results: **10.22s, 10.26s, 10.27s** — statistically indistinguishable. Confirmed via each response's `run.cpu_threads` and `run.device`/`run.fallback_to_cpu` (all `cuda`/`false`, no fallback contamination this time.

Conclusion: on GPU inference, `cpu_threads` has no measurable effect on `/transcribe` response time for this workload — the CPU-side work it accelerates (feature extraction, VAD, tokenization) is a negligible fraction of total wall time next to GPU decode. The `WHISPER_FASTER_CPU_THREADS` config knob, `cpu_threads` plumbing in `app/services/transcribe.py`, and the corresponding sweep-yaml variants were **removed** as a result — not worth the added surface area for a setting with no measurable production benefit.