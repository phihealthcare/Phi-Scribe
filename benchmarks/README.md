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
  score_transcripts.py     # compare existing JSON files
  manual/                  # put renamed TEST *.json here (gitignored)
  results/                 # output reports (gitignored)
```
