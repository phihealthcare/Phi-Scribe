# Stack test matrix (manual TEST 1, TEST 2, …)

Use the **same audio** for every test. Fix Whisper settings; change only preprocessing.

Suggested Whisper settings (keep identical across tests):

```env
WHISPER_FASTER_MODEL=small
WHISPER_FASTER_DEVICE=cuda
WHISPER_FASTER_COMPUTE_TYPE=float16
WHISPER_FASTER_LANGUAGE=pt
WHISPER_FASTER_BEAM_SIZE=5
```

Copy each transcribe JSON to `benchmarks/manual/` and rename as below, then run `score_transcripts.py`.

| Test | Save as | Stack ID | Key `.env` settings | Expected stages |
| --- | --- | --- | --- | --- |
| TEST 1 | `TEST 1.json` | baseline | all optional `false` | `normalize` |
| TEST 2 | `TEST 2.json` | hpf_only | `HPF_ENABLED=true` | `normalize`, `remove_hum` |
| TEST 3 | `TEST 3.json` | spectral | `DENOISE_ENABLED=true` | `normalize`, `denoise` |
| TEST 4 | `TEST 4.json` | rnnoise | `ENHANCE_VOICE_ENABLED=true` | `normalize`, `enhance_voice` |
| TEST 5 | `TEST 5.json` | deepfilter_isolated | `ENHANCE_DEEP_ENABLED=true`, `ENHANCE_DEEP_DEVICE=cuda`, `HPF_ENABLED=true` | `normalize`, `remove_hum`, `enhance_deep` |
| TEST 6 | `TEST 6.json` | deepfilter_post_filter | TEST 5 + `ENHANCE_DEEP_POST_FILTER=true` | + post-filter metadata |
| TEST 7 | `TEST 7.json` | deepfilter_atten_12 | TEST 5 + `ENHANCE_DEEP_ATTEN_LIM_DB=12` | same + atten limit |
| TEST 8 | `TEST 8.json` | deepfilter_loudness | TEST 5 + `LOUDNESS_ENABLED=true` | + `loudness` |
| TEST 9 | `TEST 9.json` | deepfilter_agc | TEST 5 + `AGC_ENABLED=true` | + `agc` |
| TEST 10 | `TEST 10.json` | deepfilter_full | `ENHANCE_DEEP_ENABLED=true`, `HPF_ENABLED=true`, `LPF_ENABLED=true`, `AGC_ENABLED=true`, `LOUDNESS_ENABLED=true` | full chain |
| TEST 11 | `TEST 11.json` | vad_trim | TEST 10 + `VAD_ENABLED=true` | + `vad` |

## Per-test `.env` snippets

### TEST 1 — baseline

```env
DENOISE_ENABLED=false
ENHANCE_VOICE_ENABLED=false
ENHANCE_DEEP_ENABLED=false
HPF_ENABLED=false
LPF_ENABLED=false
AGC_ENABLED=false
LOUDNESS_ENABLED=false
VAD_ENABLED=false
```

### TEST 2 — hpf_only

```env
HPF_ENABLED=true
# everything else false (as TEST 1)
```

### TEST 3 — spectral

```env
DENOISE_ENABLED=true
DENOISE_PROP_DECREASE=0.6
ENHANCE_VOICE_ENABLED=false
ENHANCE_DEEP_ENABLED=false
```

### TEST 4 — rnnoise

```env
ENHANCE_VOICE_ENABLED=true
DENOISE_ENABLED=false
ENHANCE_DEEP_ENABLED=false
```

### TEST 5 — deepfilter_isolated

```env
ENHANCE_DEEP_ENABLED=true
ENHANCE_DEEP_MODEL=DeepFilterNet3
ENHANCE_DEEP_DEVICE=cuda
ENHANCE_DEEP_POST_FILTER=false
HPF_ENABLED=true
LPF_ENABLED=false
AGC_ENABLED=false
LOUDNESS_ENABLED=false
DENOISE_ENABLED=false
ENHANCE_VOICE_ENABLED=false
VAD_ENABLED=false
```

### TEST 6 — deepfilter_post_filter

TEST 5 + `ENHANCE_DEEP_POST_FILTER=true`

### TEST 7 — deepfilter_atten_12

TEST 5 + `ENHANCE_DEEP_ATTEN_LIM_DB=12`

### TEST 8 — deepfilter_loudness

TEST 5 + `LOUDNESS_ENABLED=true`, `LOUDNESS_MODE=lufs`

### TEST 9 — deepfilter_agc

TEST 5 + `AGC_ENABLED=true`

### TEST 10 — deepfilter_full

```env
ENHANCE_DEEP_ENABLED=true
ENHANCE_DEEP_DEVICE=cuda
HPF_ENABLED=true
LPF_ENABLED=true
AGC_ENABLED=true
LOUDNESS_ENABLED=true
LOUDNESS_MODE=lufs
DENOISE_ENABLED=false
ENHANCE_VOICE_ENABLED=false
VAD_ENABLED=false
```

### TEST 11 — vad_trim

TEST 10 + `VAD_ENABLED=true`

## Compare command

```bash
mkdir -p benchmarks/manual

python benchmarks/score_transcripts.py \
  --reference benchmarks/references/anamnesia-1.txt \
  --hypothesis "benchmarks/manual/TEST*.json" \
  --output benchmarks/results/manual
```

Results: `benchmarks/results/manual/summary.md`

## Notes

- Only one enhancer per test: `denoise` **or** `enhance_voice` **or** `enhance_deep`
- If CUDA OOM on long files with DeepFilterNet, use `ENHANCE_DEEP_DEVICE=cpu` for that test and note it in your comparison
- Replace placeholder text in `benchmarks/references/anamnesia-1.txt` before drawing conclusions
