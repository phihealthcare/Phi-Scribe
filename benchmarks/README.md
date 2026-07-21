# Stack benchmark harness

Compare preprocessing stacks by scoring faster-whisper output against a **human-verified reference transcript** (WER/CER).

## Quick manual workflow (TEST 1, TEST 2, …)

Best when you change `.env`, upload, and transcribe by hand.

### 1. Create the reference script

Edit `benchmarks/references/anamnesia-1.txt` with the correct words for your audio. Lines starting with `#` are ignored.

### 2. Run each stack manually

For each stack in [STACK_MATRIX.md](STACK_MATRIX.md):

1. Update `.env`
2. Restart Flask
3. Upload the same audio
4. Transcribe: `POST /api/v1/audio/<file_id>/transcribe`
5. Copy `uploads/processed/<file_id>.json` to a compare folder and rename:

```
benchmarks/manual/TEST 1.json   # baseline
benchmarks/manual/TEST 2.json   # deepfilter_isolated
benchmarks/manual/TEST 3.json   # deepfilter_loudness
...
```

Use any label you want — the **filename** (without `.json`) becomes the row name in the report.

### 3. Compare all tests in one command

```bash
python benchmarks/score_transcripts.py \
  --reference benchmarks/references/anamnesia-1.txt \
  --hypothesis "benchmarks/manual/TEST*.json" \
  --output benchmarks/results/manual
```

Open `benchmarks/results/manual/summary.md` — stacks ranked by WER (best first).

## Automated workflow

Runs every stack in `benchmarks/stacks.yaml` without changing your `.env`.

```bash
# All stacks (slow on long audio + DeepFilterNet)
python benchmarks/run_stack_benchmark.py --stacks benchmarks/stacks.yaml

# Selected stacks only
python benchmarks/run_stack_benchmark.py --only baseline,deepfilter_isolated
```

Output: `benchmarks/results/<audio_stem>/<timestamp>/`

- `<stack_id>.json` per stack
- `summary.json` and `summary.md` ranked by WER
- When `postprocess.enabled: true` (in YAML or via `--postprocess`), each JSON includes `transcription.raw_text` (Whisper), `transcription.text` (after LLM), `scores_raw` (WER/CER before LLM), and `scores` (after LLM). `summary.md` shows both columns.

LLM postprocess is copied from `stacks.yaml` into `stacks_all_generated.yaml` when you run `generate_stacks_all.py`. Requires `LLM_BASE_URL` (default `https://api.phihc.com`) and `LLM_API_KEY` in the environment (or `.env` via `load_dotenv`).

```bash
# Full 64-stack matrix with LLM post-edit (from generated YAML)
python benchmarks/generate_stacks_all.py
export LLM_BASE_URL=https://api.phihc.com
export LLM_API_KEY=your-key
python benchmarks/run_stack_benchmark.py --stacks benchmarks/stacks_all_generated.yaml

# Or force LLM even if YAML has postprocess disabled
python benchmarks/run_stack_benchmark.py --stacks benchmarks/stacks_all_generated.yaml --postprocess
```

## Transcribe word-count benchmark

Find the preprocessing stack that maximizes how many words faster-whisper returns — **higher word count is better**. This is a proxy for capture rate, not ground-truth accuracy (more words can mean hallucinations).

Uses the full **64-stack matrix** from `generate_stacks_all.py` (spectral denoise + none only). **RNNoise** (`ENHANCE_VOICE_ENABLED`) and **DeepFilterNet** (`ENHANCE_DEEP_ENABLED`) are excluded.

Regenerate the stack matrix before a full run:

```bash
python benchmarks/generate_stacks_all.py
```

Run the benchmark (does not use `.env` — config from YAML only):

```bash
# Full matrix — all 64 stacks
python benchmarks/run_transcribe_benchmark.py

# Explicit config file
python benchmarks/run_transcribe_benchmark.py --stacks benchmarks/transcribe_stacks.yaml

# Subset for a quick test
python benchmarks/run_transcribe_benchmark.py --only baseline,spectral_hpf_agc
```

Output: `benchmarks/results/transcribe/<audio_stem>/<timestamp>/`

- Reference word count from `reference` (`.txt` transcript, same format as WER benchmark)
- Ranked by word count with Δ vs reference

**Caveats:** VAD stacks may lower word count by trimming audio. Whisper can vary slightly between runs. Consider pairing with WER/CER from `run_stack_benchmark.py` before trusting a winner.

## LLM post-edit benchmark (WER before/after)

Measure whether the optional LLM editor improves WER/CER on an existing transcript JSON (from `run_stack_benchmark.py` or the API). Requires `LLM_BASE_URL` and `LLM_API_KEY` in the environment.

```bash
export LLM_BASE_URL=https://api.phihc.com
export LLM_API_KEY=your-key

python benchmarks/run_postprocess_benchmark.py \
  --input benchmarks/results/anamnesia-4/20260617T132254Z/spectral_hpf_agc_loudness_vad.json \
  --reference benchmarks/references/anamnesia-4.txt
```

Uses `benchmarks/prompts/medical-transcript-editor.md` by default. Does not modify `run_stack_benchmark.py`.

### Save LLM before/after diff (no API call)

When postprocess runs, each stack JSON also gets a readable report:

- `benchmarks/results/.../<stack_id>.postprocess.diff.txt` — word-level changes + full BEFORE/AFTER text
- `postprocess.diff` inside the `.json` (structured changes list)

Rebuild the `.txt` report from an existing JSON:

```bash
python benchmarks/save_postprocess_diff.py \
  --input benchmarks/results/anamnesia-4/20260617T140225Z/spectral_hpf_agc_loudness_vad.json
```

## Rules for fair comparison

1. **Same audio file** for every stack
2. **Same Whisper settings** — only change preprocessing (`stacks.yaml` `whisper:` block or fixed `.env` whisper vars)
3. **One denoiser at a time** — `denoise` OR `enhance_voice` OR `enhance_deep`
4. Replace the placeholder reference text before trusting WER numbers

## WER / CER

| Metric | Meaning |
|--------|---------|
| **WER** | Word Error Rate — insertions + deletions + substitutions / reference words |
| **CER** | Character Error Rate — same at character level |

**Lower is better.** Example: WER 12% ≈ 12 errors per 100 reference words.

Scoring normalizes: lowercase, NFKC unicode, punctuation removed, whitespace collapsed.

Optional filler removal:

```bash
python benchmarks/score_transcripts.py ... --remove-fillers
```

## Speaker inference test (LLM-only, no diarization)

Test whether the LLM can assign `Autor:` / `Paciente:` **per turn** from plain Whisper text **without** acoustic diarization.
Each turn includes `rotulo`, `identificavel`, `confianca` and `motivo`. The model fills `identificacao` first, then `turnos`.

```bash
# From a flow-test or API transcript JSON (uses text + segments if present)
.venv/bin/python benchmarks/run_speaker_inference_test.py \
  --input benchmarks/results/anamnesia-3/flow-test-XXXX/result.json \
  --format all

# Or from raw text + optional segments JSON
.venv/bin/python benchmarks/run_speaker_inference_test.py \
  --text-file benchmarks/results/anamnesia-3/flow-test-XXXX/01_whisper_raw.txt \
  --segments-file path/to/segments.json \
  --format numbered
```

Formats: `plain` (one blob), `timestamped` (Whisper segment timestamps), `numbered` (`[1]` blocks), or `all`.

Outputs under `benchmarks/results/speaker-inference-<timestamp>/`:
- `00_input_*.txt` — what was sent to the LLM
- `01_result_*.json` — full JSON response + `identificacao_summary`
- `02_labeled_*.txt` — `Autor:` / `Paciente:` per turn
- `report.json` — comparison across formats

Pair with `run_flow_test.py --no-diarization` to generate `01_whisper_raw.txt` first.

## ASR fix only (improve text, no SOAP, no diarization)

Runs **only** the LLM editor prompt (`medical-transcript-editor.md`) on Whisper output.
No diarization, no Médico/Paciente labels, no SOAP.

```bash
# Full path: preprocess → Whisper → LLM improve
.venv/bin/python benchmarks/run_asr_fix_test.py

# Re-run LLM on existing Whisper text (fast)
.venv/bin/python benchmarks/run_asr_fix_test.py \
  --text-file benchmarks/results/anamnesia-3/flow-test-20260629T162404Z/01_whisper_raw.txt

# With WER scoring
.venv/bin/python benchmarks/run_asr_fix_test.py \
  --text-file path/to/01_whisper_raw.txt \
  --reference benchmarks/references/anamnesia-3.txt
```

Output: `02_llm_improved.txt` (the text you want), plus `diff.txt` and `report.json`.

Equivalent via flow test (also skips SOAP):

```bash
.venv/bin/python benchmarks/run_flow_test.py --no-diarization --no-soap
# improved text → 02_postprocess_text.txt
```

## Whisper config sweep (fixed WAV, no upload)

Compare **faster-whisper only** settings on a pre-processed WAV — no upload, no preprocess, no LLM postprocess, no SOAP.

Default audio: `uploads/processed/c07ffd25-6ebb-4262-a573-c91760d84f6e.wav` (consulta-real-1).  
Reference: `benchmarks/references/consulta-real-1.txt`.

Edit the matrix in `benchmarks/whisper_sweep_consulta-real-1.yaml` (`whisper_base` + `configs`). Swept knobs include `model`, `compute_type`, `inference_mode`, `batch_size`, `chunk_length`, `beam_size`, `vad_filter`.

```bash
# Full sweep (~11 configs; long audio + large-v3 can take 1–2 h on 6 GB GPU)
python benchmarks/run_whisper_sweep_benchmark.py

# Quick check: your current production-like stack
python benchmarks/run_whisper_sweep_benchmark.py \
  --only batched_large-v3_int8_b4

# Subset
python benchmarks/run_whisper_sweep_benchmark.py \
  --only seq_large-v3_int8,batched_large-v3_int8_b2,batched_large-v3_int8_b4
```

Output: `benchmarks/results/whisper-sweep-consulta-real-1/<timestamp>/`

- `<config_id>.json` — transcript, WER/CER, wall time, run metadata
- `<config_id>.txt` — hypothesis text
- `summary.md` / `summary.json` — ranked by WER, then wall time

`distil-large-v3` is intentionally omitted (English-only). On ~6 GB VRAM, `batch_size` above 4–6 may OOM; failed runs are logged and the sweep continues.

## Stack matrix

See [STACK_MATRIX.md](STACK_MATRIX.md) for all predefined stacks and suggested `.env` values.

## Example ranked table

| Rank | Label | WER % | CER % | Stages |
| --- | --- | ---: | ---: | --- |
| 1 | deepfilter_loudness | 8.50 | 4.20 | `normalize, remove_hum, enhance_deep, loudness` |
| 2 | deepfilter_isolated | 9.10 | 4.80 | `normalize, remove_hum, enhance_deep` |
| 3 | baseline | 14.30 | 7.10 | `normalize` |

## Files

```
benchmarks/
  stacks.yaml              # automated stack matrix
  STACK_MATRIX.md          # manual TEST 1..N guide + .env combos
  references/              # ground-truth transcripts
  score.py                 # WER/CER
  stack_config.py          # env → preprocess_audio kwargs
  run_stack_benchmark.py   # full automated run
  run_transcribe_benchmark.py  # word-count benchmark (64 stacks)
  transcribe_stacks.yaml   # transcribe benchmark config
  score_transcribe.py      # word-count scoring
  report_transcribe.py     # transcribe benchmark reports
  generate_stacks_all.py   # 64-stack matrix generator
  stacks_all_generated.yaml
  score_transcripts.py     # compare existing JSON files
  run_postprocess_benchmark.py  # LLM post-edit WER/CER before vs after
  whisper_sweep_consulta-real-1.yaml  # Whisper-only config matrix (fixed WAV)
  run_whisper_sweep_benchmark.py  # sweep inference_mode / batch / model / compute_type
  prompts/
    medical-transcript-editor.md  # production LLM editor prompt
    fix-whisper-transcript.md     # legacy specialty-specific example
  manual/                  # put renamed TEST *.json here (gitignored)
  results/                 # output reports (gitignored)
```
