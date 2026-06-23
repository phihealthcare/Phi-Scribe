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

LLM postprocess is copied from `stacks.yaml` into `stacks_all_generated.yaml` when you run `generate_stacks_all.py`. Requires `OPENAI_API_KEY` in the environment (or `.env` via `load_dotenv`).

```bash
# Full 64-stack matrix with LLM post-edit (from generated YAML)
python benchmarks/generate_stacks_all.py
export OPENAI_API_KEY=sk-...
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

Measure whether the optional LLM editor improves WER/CER on an existing transcript JSON (from `run_stack_benchmark.py` or the API). Requires `OPENAI_API_KEY` in the environment.

```bash
export OPENAI_API_KEY=sk-...

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
  prompts/
    medical-transcript-editor.md  # production LLM editor prompt
    fix-whisper-transcript.md     # legacy specialty-specific example
  manual/                  # put renamed TEST *.json here (gitignored)
  results/                 # output reports (gitignored)
```
