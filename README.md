## TO-DO

[X] Standardize input format (WAV/PCM);

[X] Normalize to mono channel and resample to 16 kHz;

[X] Implement noise reduction based on Spectral Gating (`noisereduce`);

[ ] Implement RNNoise to test alongside other possible stacks;

[ ] Implement DeepFilterNet to test alongside other possible stacks;

[ ] Create high-pass/low-pass filters (remove low-frequency noise: 50/60 Hz hum and sibilance);

[ ] Apply gain and loudness normalization;

[ ] Evaluate automatic gain control (AGC);

[X] Apply silence handling and initial segmentation with VAD;

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

---

### RNNoise

Lightweight neural network (Xiph/Mozilla) for **real-time voice enhancement**, designed for VoIP.


|              |                                                            |
| ------------ | ---------------------------------------------------------- |
| **Label**    | `enhance_voice`                                            |
| **Good for** | Human voice + moderate background noise, low latency       |
| **Bad for**  | Already clean audio; rare medical terms without validation |
| **Cost**     | Low (CPU)                                                  |
| **Note**     | Trained mainly at 48 kHz — may require resampling          |


---

### DeepFilterNet

**Deep learning** model (PyTorch) for speech enhancement — a reference in many complex noise scenarios.


|              |                                                                    |
| ------------ | ------------------------------------------------------------------ |
| **Label**    | `enhance_deep`                                                     |
| **Good for** | **Non-stationary** noise, difficult recordings, offline processing |
| **Bad for**  | Fast MVP, servers without GPU, already decent audio                |
| **Cost**     | High (PyTorch, memory, inference time)                             |


---

### High-pass / low-pass filters

Classic DSP filters that cut frequency bands.

#### High-pass (HPF) — `remove_hum`

- Removes energy in **low frequencies**.
- Target: **50/60 Hz hum** (mains: 50 Hz in Brazil/Europe, 60 Hz in the US), rumble, desk vibration.
- Suggested cutoff: **80–100 Hz** (conservative for speech).

#### Low-pass (LPF) — `reduce_sibilance`

- Removes energy in **high frequencies**.
- Target: **sibilance** (“s”, “sh”), excessive microphone hiss.
- Suggested cutoff: **10–12 kHz** (ideally before resampling to 16 kHz).
- **Caution:** cutting too much removes consonants Whisper needs.

**Recommended order:** HPF/LPF **before** spectral denoise, after or together with `normalize`.

---

### LUFS (Loudness Units Full Scale)

Measure of **perceived volume** (loudness), not just peak amplitude.

- Used in broadcast and podcast for consistent levels.
- **LUFS normalization** equalizes perceived volume across recordings (e.g. **−23 LUFS** target for speech).
- Better than peak normalization when speakers or recordings vary widely.


|              |                                                                    |
| ------------ | ------------------------------------------------------------------ |
| **Label**    | `loudness`                                                         |
| **Good for** | Consultations with irregular volume across segments or microphones |
| **Tools**    | `ffmpeg` (`loudnorm`), `pyloudnorm`                                |


---

### AGC (Automatic Gain Control)

**Automatic gain control** — amplifies quiet segments and attenuates loud ones over time.


|                          |                                                           |
| ------------------------ | --------------------------------------------------------- |
| **Label**                | `agc`                                                     |
| **Good for**             | Speaker far from the microphone, highly irregular volume  |
| **Risk**                 | Raises background noise during silences; “pumping” effect |
| **Difference from LUFS** | AGC is **dynamic**; LUFS is **global** per segment/file   |


Use in moderation on clinical audio — background noise may rise along with voice.

---

### VAD (Voice Activity Detection)

Detects **speech segments** vs. silence/noise.


|                    |                                                                  |
| ------------------ | ---------------------------------------------------------------- |
| **Label**          | `vad`                                                            |
| **Implementation** | Silero VAD (`trim` — removes long silences, concatenates speech) |
| **Good for**       | Trimming long silences, reducing Whisper inference cost          |
| **Risk**           | Cutting word beginnings/endings; losing quiet speech             |
| **Enable**         | `VAD_ENABLED=true` in `.env`                                     |


VAD is optional and should be validated so clinically relevant speech is not removed.

---

## How the techniques complement each other


| Layer                | Technique         | Problem type                              |
| -------------------- | ----------------- | ----------------------------------------- |
| `normalize`          | ffmpeg            | Wrong format (stereo, sample rate, codec) |
| `remove_hum`         | HPF ~80 Hz        | 50/60 Hz hum, rumble                      |
| `reduce_sibilance`   | LPF ~10 kHz       | Excessive sibilance                       |
| `loudness`           | LUFS              | Inconsistent perceived volume             |
| `agc`                | Compressor/AGC    | Segments too quiet/loud                   |
| `denoise_stationary` | noisereduce       | Steady hiss                               |
| `enhance_voice`      | RNNoise           | Room noise on voice                       |
| `enhance_deep`       | DeepFilterNet     | Complex noise                             |
| `vad`                | Silero VAD (trim) | Long silences                             |


**Rule:** do not stack all layers at maximum strength — validate with real transcription (WER or manual review).

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

**System dependency:** `ffmpeg` (audio conversion).

**Optional preprocessing variables** (`.env`):


| Variable                      | Default | Description                                                    |
| ----------------------------- | ------- | -------------------------------------------------------------- |
| `DENOISE_ENABLED`             | `false` | Enables spectral reduction (`noisereduce`)                     |
| `DENOISE_PROP_DECREASE`       | `0.6`   | Denoise strength (0.0–1.0)                                     |
| `VAD_ENABLED`                 | `false` | Enables Silero VAD (trim long silences)                        |
| `VAD_THRESHOLD`               | `0.5`   | Speech probability threshold                                   |
| `VAD_MIN_SPEECH_DURATION_MS`  | `250`   | Minimum duration of a speech segment                           |
| `VAD_MIN_SILENCE_DURATION_MS` | `1000`  | Minimum silence to split segments (short pauses are preserved) |
| `VAD_SPEECH_PAD_MS`           | `300`   | Padding before/after each speech segment                       |


### Main endpoint

```
POST /api/v1/audio/upload
Content-Type: multipart/form-data
Field: file (MP3 or WAV)
```

### Project structure

```
app/
  routes/audio.py              # upload endpoints
  services/audio_processor.py  # preprocess_audio (normalize, denoise, vad)
  services/vad.py              # Silero VAD trim
  config.py                    # environment variables
uploads/                         # original audio
uploads/processed/               # processed WAV + PCM
```

---

## References

- [Whisper](https://github.com/openai/whisper)
- [noisereduce](https://github.com/timsainb/noisereduce)
- [RNNoise](https://github.com/xiph/rnnoise)
- [DeepFilterNet](https://github.com/Rikorose/DeepFilterNet)
- [ffmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm)

