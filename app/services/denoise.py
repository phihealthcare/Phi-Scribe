import wave
from pathlib import Path

import noisereduce as nr
import numpy as np

from app.services.normalize import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH

def apply_stationary(wav_path: Path, prop_decrease: float = 0.6) -> Path:
    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()

        if sample_rate != SAMPLE_RATE or channels != CHANNELS or sample_width != SAMPLE_WIDTH:
            raise ValueError("Unexpected WAV format for denoise step")

        audio = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)
        audio = audio.astype(np.float32) / 32768.0

    reduced = nr.reduce_noise(
        y=audio,
        sr=sample_rate,
        prop_decrease=prop_decrease,
        stationary=True,
    )
    
    reduced_int16 = np.clip(reduced * 32768.0, -32768, 32767).astype(np.int16)

    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(reduced_int16.tobytes())

    return wav_path
