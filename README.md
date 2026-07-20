## TO-DO

[X] Standardize input format (WAV/PCM);

[X] Normalize to mono channel and resample to 16 kHz;

[X] Implement noise reduction based on Spectral Gating (`noisereduce`);

[X] Implement RNNoise to test alongside other possible stacks;

[X] Implement DeepFilterNet to test alongside other possible stacks;

[X] Create high-pass/low-pass filters (remove low-frequency noise: 50/60 Hz hum and sibilance);

[X] Apply gain and loudness normalization;

[X] Evaluate automatic gain control (AGC);

[X] Apply silence handling and initial segmentation with VAD;

[X] Add experimental faster-whisper for local stack testing (production will use OpenAI Whisper API);

---

## For Developer

### Whisper

OpenAI **speech-to-text** model. Converts audio to text.

- Expects **mono**, **16 kHz**, PCM format.
- Is relatively robust to moderate noise — aggressive denoising can **worsen** transcription.
- In phi-scribe, it is the final destination of the preprocessing pipeline.

**When to use:** after `normalize` and, optionally, after cleanup stages validated with real audio.

---

### Spectral gating (`noisereduce`)

**Spectral noise reduction** technique. Estimates the noise profile (silent segments) and attenuates frequencies below a threshold in the spectrogram.


|              |                                                              |
| ------------ | ------------------------------------------------------------ |
| **Label**    | `denoise_stationary`                                         |
| **Good for** | **Steady** noise (AC, fan, stable hiss)                      |
| **Bad for**  | Variable noise (keyboard, doors, multiple voices)            |
| **Cost**     | Low (CPU, pure Python)                                       |
| **Risk**     | “Musical noise” artifacts; cuts consonants if too aggressive |


**Typical parameters:** `prop_decrease=0.5–0.7` (avoid 1.0).

**Mutual exclusion:** do not enable together with `ENHANCE_VOICE_ENABLED` or `ENHANCE_DEEP_ENABLED` — spectral gating (`denoise`), RNNoise (`enhance_voice`), and DeepFilterNet (`enhance_deep`) are alternative noise-reduction stacks. Precedence if multiple are `true`: `enhance_deep` > `enhance_voice` > `denoise`.

---

### RNNoise

Lightweight neural network (Xiph/Mozilla) for **real-time voice enhancement**, designed for VoIP.


|                    |                                                                    |
| ------------------ | ------------------------------------------------------------------ |
| **Label**          | `enhance_voice`                                                    |
| **Implementation** | `pyrnnoise` (CPU, 16 kHz pipeline with internal 48 kHz processing) |
| **Good for**       | Human voice + moderate background noise, low latency               |
| **Bad for**        | Already clean audio; rare medical terms without validation         |
| **Cost**           | Low (CPU)                                                          |
| **Enable**         | `ENHANCE_VOICE_ENABLED=true` in `.env`                             |
| **Pipeline**       | After filters, before `agc` — same slot as `denoise`               |


**Difference from `denoise`:** spectral gating (`noisereduce`) vs neural VoIP enhancer — **do not enable both**. For isolated RNNoise testing, also turn off `AGC_ENABLED`, `LOUDNESS_ENABLED`, `LPF_ENABLED`, and `ENHANCE_DEEP_ENABLED`.

---

### DeepFilterNet

**Deep learning** model (PyTorch) for speech enhancement — a reference in many complex noise scenarios.


|                    |                                                                        |
| ------------------ | ---------------------------------------------------------------------- |
| **Label**          | `enhance_deep`                                                         |
| **Implementation** | `deepfilternet` (PyTorch, 48 kHz native, resampled in pipeline)        |
| **Good for**       | **Non-stationary** noise, difficult recordings, offline processing     |
| **Bad for**        | Fast MVP, servers without GPU, already decent audio                    |
| **Cost**           | High (PyTorch, memory, inference time; GPU recommended)                |
| **Enable**         | `ENHANCE_DEEP_ENABLED=true` in `.env`                                  |
| **Pipeline**       | After filters, before `agc` — same slot as `denoise` / `enhance_voice` |


**Difference from other denoisers:** `denoise` = spectral gating; `enhance_voice` = light RNNoise (CPU); `enhance_deep` = heavy deep model. **Enable only one.** First run may download the pretrained model (~tens of MB). Building `deepfilterlib` requires **Rust** on some platforms.

For isolated DeepFilterNet testing, turn off `DENOISE_ENABLED`, `ENHANCE_VOICE_ENABLED`, and ideally `AGC_ENABLED`, `LOUDNESS_ENABLED`, `LPF_ENABLED`.

On CUDA, long files are processed in ~15 s chunks to limit VRAM use. If GPU memory is still exhausted, the stage automatically retries on CPU (`fallback_reason: cuda_oom`).

---

### High-pass / low-pass filters

Classic DSP filters that cut frequency bands.

#### High-pass (HPF) — `remove_hum`

- Removes energy in **low frequencies**.
- Target: **50/60 Hz hum** (mains: 50 Hz in Brazil/Europe, 60 Hz in the US), rumble, desk vibration.
- Suggested cutoff: **80–100 Hz** (conservative for speech).
- **Enable:** `HPF_ENABLED=true`, `HPF_CUTOFF_HZ=80`

#### Low-pass (LPF) — `reduce_sibilance`

- Removes energy in **high frequencies**.
- Target: **sibilance** (“s”, “sh”), excessive microphone hiss.
- At **16 kHz** (after normalize), use **~7000–7500 Hz** — not 10–12 kHz (Nyquist is 8 kHz).
- **Enable:** `LPF_ENABLED=true`, `LPF_CUTOFF_HZ=7500`

**Recommended order:** HPF/LPF **before** spectral denoise, after or together with `normalize`.

---

### LUFS (Loudness Units Full Scale)

Measure of **perceived volume** (loudness), not just peak amplitude.

- Used in broadcast and podcast for consistent levels.
- **LUFS normalization** equalizes perceived volume across recordings (e.g. **−23 LUFS** for speech).
- Better than peak normalization when speakers or recordings vary widely.


|                    |                                                                   |
| ------------------ | ----------------------------------------------------------------- |
| **Label**          | `loudness`                                                        |
| **Implementation** | `lufs` mode (ffmpeg `loudnorm`) or `peak` mode (max-peak scaling) |
| **Good for**       | Consultations with irregular volume between files or microphones  |
| **Enable**         | `LOUDNESS_ENABLED=true`, `LOUDNESS_MODE=lufs` or `peak`           |
| **Pipeline**       | After `agc`, before `vad`                                         |


`**peak` mode** is simpler but less representative of perceived loudness than LUFS.

---

### AGC (Automatic Gain Control)

**Automatic gain control** — amplifies quiet segments and attenuates loud ones over time.


|                          |                                                           |
| ------------------------ | --------------------------------------------------------- |
| **Label**                | `agc`                                                     |
| **Implementation**       | RMS-based dynamic gain (scipy/numpy), after denoise       |
| **Good for**             | Speaker far from the microphone, highly irregular volume  |
| **Risk**                 | Raises background noise during silences; “pumping” effect |
| **Difference from LUFS** | AGC is **dynamic**; LUFS is **global** per segment/file   |
| **Enable**               | `AGC_ENABLED=true` in `.env`                              |


Use in moderation on clinical audio — background noise may rise along with voice. **LUFS loudness normalization is implemented** as optional stage `loudness` (separate from AGC).

**Pipeline position:** after `denoise`, before `loudness` and `vad`.

---

### VAD (Voice Activity Detection)

Detects **speech segments** vs. silence/noise.


|                    |                                                                  |
| ------------------ | ---------------------------------------------------------------- |
| **Label**          | `vad`                                                            |
| **Implementation** | Silero VAD, ONNX Runtime backend (`trim` — removes long silences, concatenates speech). CPU-only by design (~2.2x faster than the TorchScript backend for this call pattern — see `app/services/vad.py`); same model weights, identical output. |
| **Good for**       | Trimming long silences, reducing Whisper inference cost          |
| **Risk**           | Cutting word beginnings/endings; losing quiet speech             |
| **Enable**         | `VAD_ENABLED=true` in `.env`                                     |


VAD is optional and should be validated so clinically relevant speech is not removed.

---

## How the techniques complement each other


| Layer                | Technique          | Problem type                               |
| -------------------- | ------------------ | ------------------------------------------ |
| `normalize`          | ffmpeg             | Wrong format (stereo, sample rate, codec)  |
| `remove_hum`         | HPF ~80 Hz (scipy) | 50/60 Hz hum, rumble                       |
| `reduce_sibilance`   | LPF ~7.5 kHz       | Excessive sibilance (16 kHz audio)         |
| `denoise_stationary` | noisereduce        | Steady hiss                                |
| `agc`                | RMS compressor     | Segments too quiet/loud                    |
| `loudness`           | LUFS / peak        | Inconsistent perceived volume across files |
| `enhance_voice`      | RNNoise            | Room noise on voice                        |
| `enhance_deep`       | DeepFilterNet      | Complex noise                              |
| `vad`                | Silero VAD (trim)  | Long silences                              |


**Rule:** do not stack all layers at maximum strength — validate with real transcription (WER or manual review).

---

## Stack compatibility matrix (rows × columns)

**Legend:** ✅ = can be used together in the same pipeline · ❌ = mutually exclusive or the column flag has no effect · — = same stage

`normalize` always runs; it is included as a row/column for completeness.

**Pipeline order:** `normalize` → `HPF` / `LPF` → **one denoiser** → `AGC` → `loudness` → `VAD`

**Denoiser rule:** only one of `denoise`, `enhance_voice`, `enhance_deep` runs. If multiple are `true`: `enhance_deep` > `enhance_voice` > `denoise`.


|                 | norm | HPF | LPF | denoise | RNNoise | DeepFilter | post_filter | atten_lim | AGC | loudness | VAD |
| --------------- | ---- | --- | --- | ------- | ------- | ---------- | ----------- | --------- | --- | -------- | --- |
| **normalize**   | —    | ✅   | ✅   | ✅       | ✅       | ✅          | ✅           | ✅         | ✅   | ✅        | ✅   |
| **HPF**         | ✅    | —   | ✅   | ✅       | ✅       | ✅          | ✅           | ✅         | ✅   | ✅        | ✅   |
| **LPF**         | ✅    | ✅   | —   | ✅       | ✅       | ✅          | ✅           | ✅         | ✅   | ✅        | ✅   |
| **denoise**     | ✅    | ✅   | ✅   | —       | ❌       | ❌          | ❌           | ❌         | ✅   | ✅        | ✅   |
| **RNNoise**     | ✅    | ✅   | ✅   | ❌       | —       | ❌          | ❌           | ❌         | ✅   | ✅        | ✅   |
| **DeepFilter**  | ✅    | ✅   | ✅   | ❌       | ❌       | —          | ✅           | ✅         | ✅   | ✅        | ✅   |
| **post_filter** | ✅    | ✅   | ✅   | ❌       | ❌       | ✅          | —           | ✅         | ✅   | ✅        | ✅   |
| **atten_lim**   | ✅    | ✅   | ✅   | ❌       | ❌       | ✅          | ✅           | —         | ✅   | ✅        | ✅   |
| **AGC**         | ✅    | ✅   | ✅   | ✅       | ✅       | ✅          | ✅           | ✅         | —   | ✅        | ✅   |
| **loudness**    | ✅    | ✅   | ✅   | ✅       | ✅       | ✅          | ✅           | ✅         | ✅   | —        | ✅   |
| **VAD**         | ✅    | ✅   | ✅   | ✅       | ✅       | ✅          | ✅           | ✅         | ✅   | ✅        | —   |


## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

**Use Python 3.12** (3.13 also works), not whatever `python3` defaults to on a newer system, and not older either — two constraints pull in opposite directions: `nemo_toolkit[asr]`'s dependency resolution forces an older `numba` that has no prebuilt wheel for 3.14 and refuses to build from source on it (`Cannot install on Python version 3.14; only versions >=3.10,<3.14 are supported`), while `app/services/soap_draft.py` uses a multi-line f-string expression that's a `SyntaxError` on 3.11 and below (needs PEP 701's relaxed f-string grammar, Python 3.12+). The Docker image (below) is pinned to `python:3.12-slim` for the same reasons — if your existing local `.venv` was created with a different Python version, recreate it with 3.12 before running `pip install -r requirements.txt`.

`faster-whisper`, `torch`, `nemo_toolkit[asr]` (Sortformer diarization), and `nvidia-cublas-cu12` are already included in `requirements.txt` — no separate install step needed, and no separate virtualenv either (see below).

For **GPU** (`WHISPER_FASTER_DEVICE=cuda`), `nvidia-cublas-cu12` is needed because `faster-whisper` uses CUDA 12 libraries while PyTorch (Silero VAD) uses CUDA 13. Without it you may see: `Library libcublas.so.12 is not found`.

Production will use the **OpenAI Whisper API** wired to our LLM. `faster-whisper` is decoupled and only used to evaluate preprocessing stacks locally.

**System dependency:** `ffmpeg` (audio conversion). Sortformer (below) additionally needs `sox`.

**Diarization backend:** [NVIDIA NeMo Sortformer](https://huggingface.co/nvidia/diar_sortformer_4spk-v1) (`DIARIZATION_BACKEND=sortformer`, the only backend now — `pyannote.audio` has been removed). It runs via subprocess (`benchmarks/sortformer_worker.py` / `sortformer_daemon.py`, see `app/services/diarization_sortformer.py`) but **in the same `.venv`** as everything else — that subprocess design used to exist so `nemo_toolkit` could be isolated in its own `.venv-sortformer/` away from `pyannote.audio`'s conflicting dependencies (protobuf/onnx version clash). Now that `pyannote.audio` is gone, there's nothing left to conflict with, so `nemo_toolkit[asr]` just installs into the main `.venv`, and the subprocess defaults to `sys.executable` — the same interpreter running the Flask app — automatically, in both Docker and local dev. `SORTFORMER_VENV_PYTHON` only needs setting if you deliberately want a different interpreter.

If you have a leftover `.venv-sortformer/` from before this change, it's no longer used and can be deleted.

### Docker

Runs the backend (Flask) and frontend (Vite build served by nginx, which
proxies `/api/` to the backend so there's no cross-origin setup needed —
CORS is only enabled when `FLASK_ENV=development`) as two containers:

```bash
cp .env.example .env   # fill in LLM_API_KEY, HF_TOKEN, etc.
# .env.example defaults to FLASK_ENV=development; env_file in docker-compose.yml
# overrides the image's own ENV, so set this explicitly for a real deployment:
#   FLASK_ENV=production
docker compose up --build
```

Frontend: `http://localhost` · Backend API: `http://localhost:5000/api/v1/audio`.

**Sortformer model cache:** the backend's `nemo_cache` volume (`docker-compose.yml`) persists Sortformer's downloaded model weights (several GB) across container recreates — without it, every `docker compose up --build` would re-download them.

**GPU:** `docker-compose.yml` requests a GPU for the backend by default
(`WHISPER_FASTER_DEVICE=cuda` / `SORTFORMER_DEVICE=cuda` in `.env`). This
needs the [NVIDIA Container Toolkit](https://github.com/NVIDIA/nvidia-container-toolkit)
on the host — no CUDA toolkit is baked into the image; the `torch` wheel
already bundles its own CUDA runtime, the toolkit just exposes the host GPU
to the container. For CPU-only, delete the `deploy:` block in
`docker-compose.yml` and set `WHISPER_FASTER_DEVICE=cpu` /
`SORTFORMER_DEVICE=cpu` in `.env`.

**Cloud deployment:** the two images (`Dockerfile` for the backend,
`frontend/Dockerfile` for the frontend) are plain Docker images with no
platform-specific dependencies, so they run on any container host that
offers a GPU node — ECS/EC2, GKE, Lambda Labs, RunPod, etc. Push both images
to a registry, run the backend on a GPU-enabled node (or `WHISPER_FASTER_DEVICE=cpu`
without one), and point the frontend build's `VITE_API_BASE_URL` build arg
at wherever the backend is reachable if it isn't behind the same nginx proxy.

**Optional preprocessing variables** (`.env`):


| Variable                | Default          | Description                                                 |
| ----------------------- | ---------------- | ----------------------------------------------------------- |
| `DENOISE_ENABLED`       | `false`          | Enables spectral reduction (`noisereduce`)                  |
| `DENOISE_PROP_DECREASE` | `0.6`            | Denoise strength (0.0–1.0)                                  |
| `ENHANCE_VOICE_ENABLED` | `false`          | RNNoise voice enhancement (`enhance_voice`) — after filters |
| `ENHANCE_DEEP_ENABLED`  | `false`          | DeepFilterNet (`enhance_deep`) — after filters, before AGC  |
| `ENHANCE_DEEP_MODEL`    | `DeepFilterNet3` | Pretrained model name or local model directory              |
| `ENHANCE_DEEP_DEVICE`   | `cpu`            | `cpu` or `cuda` (falls back to CPU if CUDA unavailable)     |


Upload metadata includes `requested_device`, resolved `device`, `model_device`, `cuda_available`, `fallback_to_cpu`, `fallback_reason` (`cuda_oom` when applicable), and `chunked` / `chunks_processed` for long CUDA runs.

| `ENHANCE_DEEP_POST_FILTER`    | `false` | Slightly more aggressive noise suppression                     |
| `ENHANCE_DEEP_ATTEN_LIM_DB`   | (unset) | Optional attenuation limit in dB                               |
| `HPF_ENABLED`                 | `false` | High-pass filter (`remove_hum`)                                |
| `HPF_CUTOFF_HZ`               | `80`    | HPF cutoff in Hz                                               |
| `LPF_ENABLED`                 | `false` | Low-pass filter (`reduce_sibilance`)                           |
| `LPF_CUTOFF_HZ`               | `7500`  | LPF cutoff in Hz (use ~7–7.5 kHz at 16 kHz sample rate)        |
| `AGC_ENABLED`                 | `false` | Dynamic gain control (`agc`) — after denoise, before VAD       |
| `AGC_TARGET_DBFS`             | `-20`   | Target RMS level in dBFS                                       |
| `AGC_MAX_GAIN_DB`             | `12`    | Max boost in dB (higher values raise background noise)         |
| `AGC_WINDOW_MS`               | `30`    | RMS analysis window in ms                                      |
| `LOUDNESS_ENABLED`            | `false` | Global loudness normalization (`loudness`) — after AGC       |
| `LOUDNESS_MODE`               | `lufs`  | `lufs` (ffmpeg loudnorm) or `peak` (max-peak scaling)          |
| `LOUDNESS_TARGET_LUFS`        | `-23`   | Target integrated loudness in LUFS mode                        |
| `LOUDNESS_TRUE_PEAK`          | `-1.5`  | True peak limit (dBTP) in LUFS mode                             |
| `LOUDNESS_LRA`                | `11`    | Loudness range in LUFS mode                                    |
| `LOUDNESS_PEAK_TARGET_DBFS`   | `-1.0`  | Target peak in dBFS for peak mode                              |
| `VAD_ENABLED`                 | `false` | Enables Silero VAD (trim long silences)                        |
| `VAD_THRESHOLD`               | `0.5`   | Speech probability threshold                                   |
| `VAD_MIN_SPEECH_DURATION_MS`  | `250`   | Minimum duration of a speech segment                           |
| `VAD_MIN_SILENCE_DURATION_MS` | `1000`  | Minimum silence to split segments (short pauses are preserved) |
| `VAD_SPEECH_PAD_MS`           | `300`   | Padding before/after each speech segment                       |

**Experimental transcription variables** (`.env`, local testing only):


| Variable                                         | Default       | Description                                                                                                          |
| ------------------------------------------------ | ------------- | -------------------------------------------------------------------------------------------------------------------- |
| `WHISPER_FASTER_ENABLED`                         | `false`       | Enables `POST /api/v1/audio/<file_id>/transcribe`                                                                    |
| `WHISPER_FASTER_MODEL`                           | `small`       | Model: `tiny`, `base`, `small`, `medium`, `large-v3`, `distil-large-v3`, `distil-large-v3.5`, `turbo`, or HF repo id |
| `WHISPER_FASTER_DEVICE`                          | `cpu`         | `cpu` or `cuda`                                                                                                      |
| `WHISPER_FASTER_COMPUTE_TYPE`                    | `int8`        | `int8` (CPU), `float16` (GPU)                                                                                        |
| `WHISPER_FASTER_LANGUAGE`                        | `pt`          | Language code                                                                                                        |
| `WHISPER_FASTER_BEAM_SIZE`                       | `5`           | Beam search width                                                                                                    |
| `WHISPER_FASTER_INITIAL_PROMPT`                  | (clinical PT) | Optional prompt for medical Portuguese                                                                               |
| `WHISPER_FASTER_COMPRESSION_RATIO_THRESHOLD`     | `2.4`         | Reject repetitive segments above this gzip ratio (lower = stricter)                                                  |
| `WHISPER_FASTER_LOG_PROB_THRESHOLD`              | `-1.0`        | Reject low-confidence segments (higher = stricter, e.g. `-0.8`)                                                      |
| `WHISPER_FASTER_HALLUCINATION_SILENCE_THRESHOLD` | (unset)       | Skip suspected hallucinations after N seconds of silence                                                             |
| `WHISPER_FASTER_CONDITION_ON_PREVIOUS_TEXT`      | `true`        | Use prior segment as context (`false` can reduce repetition on long files)                                           |
| `WHISPER_FASTER_VAD_FILTER`                      | `false`       | faster-whisper internal VAD (separate from upload `VAD_ENABLED`)                                                     |


**LLM transcript post-edit** (optional, after Whisper — `.env`):


| Variable                             | Default                                           | Description                                                                                            |
| ------------------------------------ | ------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `TRANSCRIPT_POSTPROCESS_ENABLED`     | `false`                                           | Run LLM editor on Whisper output before returning `transcription.text`                                 |
| `ASR_FIX_ENABLED`                    | `true`                                            | When postprocess is on, run step 04 ASR fix; set `false` to skip ASR fix and feed Whisper text to SOAP |
| `TRANSCRIPT_POSTPROCESS_PROVIDER`    | `phihc`                                           | Provider label (informational)                                                                         |
| `LLM_BASE_URL`                       | `https://api.phihc.com`                           | PhiHC API host; requests go to `/api/medgemma`                                                         |
| `LLM_API_KEY`                        | (required when postprocess enabled)               | Bearer token for PhiHC MedGemma API                                                                    |
| `TRANSCRIPT_POSTPROCESS_MODEL`       | `gemma3:12b-it-qat`                               | Chat model for post-edit and SOAP draft                                                                |
| `TRANSCRIPT_POSTPROCESS_PROMPT_PATH` | `benchmarks/prompts/medical-transcript-editor.md` | System prompt file (specialty-agnostic pt-BR medical editor)                                           |
| `SOAP_DRAFT_PROMPT_PATH`             | `benchmarks/prompts/soap-draft.md`                | SOAP draft system prompt (runs when postprocess is enabled)                                            |


When `TRANSCRIPT_POSTPROCESS_ENABLED=false`, transcribe responses are unchanged. When enabled, `transcription.text` is the corrected transcript and `transcription.raw_text` holds the raw Whisper output. On LLM failure, `transcription.text` stays raw and `postprocess.error` describes the failure.

Pipeline:

```
upload (preprocess) → transcribe_wav (faster-whisper) → [optional] LLM editor → API response
```

Prompt: [benchmarks/prompts/medical-transcript-editor.md](benchmarks/prompts/medical-transcript-editor.md).

```
POST /api/v1/audio/upload
Content-Type: multipart/form-data
Field: file (MP3, WAV, or MP4)
```

```
POST /api/v1/audio/<file_id>/transcribe
```

Experimental — transcribes an already processed WAV (`uploads/processed/<file_id>.wav`) from a prior `/upload`. `<file_id>` is the UUID returned by upload, **not** the original filename.

```
POST /api/v1/audio/public/<stem>/transcribe
```

Raw transcription — reads `public/<stem>.mp3`, `.wav`, or `.mp4` directly. **No preprocessing.** Example: `POST /api/v1/audio/public/anamnesia-1/transcribe` uses `public/anamnesia-1.mp3`.

```
POST /api/v1/audio/transcribe/raw
Content-Type: multipart/form-data
Field: file (MP3, WAV, or MP4)
```

Raw transcription — transcribes the uploaded file as-is. **No preprocessing.**

On CUDA OOM (common when `WHISPER_FASTER_MODEL=medium`/`large-v3` after DeepFilterNet upload), transcription automatically retries on CPU (`whisper.fallback_to_cpu: true`, `fallback_reason: cuda_oom`). GPU memory from DeepFilterNet is released before loading Whisper. For faster GPU runs, use `small` or `base`, or set `ENHANCE_DEEP_DEVICE=cpu` during upload.

### Experimental: faster-whisper (local testing only)

Use this workflow to compare how preprocessing affects transcription:

1. Upload the same audio with different `.env` combos (`HPF_ENABLED`, `LPF_ENABLED`, `DENOISE_ENABLED`, `ENHANCE_VOICE_ENABLED`, `ENHANCE_DEEP_ENABLED`, `AGC_ENABLED`, `LOUDNESS_ENABLED`, `LOUDNESS_MODE`, `VAD_ENABLED`, etc.)
2. Note each `file_id` from the upload response
3. Enable `WHISPER_FASTER_ENABLED=true` and call `POST /api/v1/audio/<file_id>/transcribe`
4. Compare `uploads/processed/<file_id>.json` transcripts

Upload and preprocessing work independently of Whisper. Transcription is a separate, optional step.

**Suggested A/B stacks:**


| Stack            | Settings                                                                            |
| ---------------- | ----------------------------------------------------------------------------------- |
| Baseline         | all optional stages `false`                                                         |
| Spectral denoise | `DENOISE_ENABLED=true`, `ENHANCE_VOICE_ENABLED=false`, `ENHANCE_DEEP_ENABLED=false` |
| RNNoise          | `ENHANCE_VOICE_ENABLED=true`, `DENOISE_ENABLED=false`, `ENHANCE_DEEP_ENABLED=false` |
| DeepFilterNet    | `ENHANCE_DEEP_ENABLED=true`, `DENOISE_ENABLED=false`, `ENHANCE_VOICE_ENABLED=false` |


If multiple enhancer flags are `true`, precedence is: `enhance_deep` > `enhance_voice` > `denoise`.

### Stack benchmark (WER/CER)

Compare preprocessing stacks against a reference transcript. See [benchmarks/README.md](benchmarks/README.md) and [benchmarks/STACK_MATRIX.md](benchmarks/STACK_MATRIX.md) for manual **TEST 1, TEST 2, …** workflow or automated runs.

```bash
python benchmarks/score_transcripts.py \
  --reference benchmarks/references/anamnesia-1.txt \
  --hypothesis "benchmarks/manual/TEST*.json" \
  --output benchmarks/results/manual
```

### Project structure

```
app/
  routes/audio.py              # upload + experimental transcribe endpoints
  services/audio_processor.py  # preprocess_audio (normalize, filters, denoise/enhancers, agc, loudness, vad)
  services/filters.py          # HPF/LPF (remove_hum, reduce_sibilance)
  services/enhance_voice.py    # RNNoise voice enhancement
  services/enhance_deep.py       # DeepFilterNet speech enhancement
  services/agc.py              # dynamic gain (RMS AGC)
  services/loudness.py         # LUFS / peak loudness normalization
  services/transcribe.py       # experimental faster-whisper (decoupled)
  services/transcript_postprocess.py  # optional LLM post-edit after Whisper
  services/vad.py              # Silero VAD trim
  config.py                    # environment variables
uploads/                         # original audio
uploads/processed/               # processed WAV + PCM + optional .json transcripts
benchmarks/                      # stack WER/CER harness (see benchmarks/README.md)
```

---

## References

- [Whisper](https://github.com/openai/whisper)
- [noisereduce](https://github.com/timsainb/noisereduce)
- [RNNoise](https://github.com/xiph/rnnoise)
- [DeepFilterNet](https://github.com/Rikorose/DeepFilterNet)
- [ffmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)

