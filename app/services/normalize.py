import subprocess
import wave
from pathlib import Path

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2

def _apply_filters(input_path: Path, output_path: Path, output_format: str | None = None) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-ac",
        str(CHANNELS),
        "-ar",
        str(SAMPLE_RATE),
        "-sample_fmt",
        "s16",
    ]

    if output_format:
        command.extend(["-f", output_format])

    command.append(str(output_path))

    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )


def normalize_audio(input_path: Path, output_wav_path: Path) -> Path:
    output_wav_path.parent.mkdir(parents=True, exist_ok=True)
    _apply_filters(input_path, output_wav_path)
    return output_wav_path


def export_pcm(wav_path: Path, output_pcm_path: Path) -> Path:
    output_pcm_path.parent.mkdir(parents=True, exist_ok=True)
    _apply_filters(wav_path, output_pcm_path, output_format="s16le")
    return output_pcm_path


def read_audio_metadata(wav_path: Path) -> dict:
    with wave.open(str(wav_path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        duration_ms = int(wav_file.getnframes() / sample_rate * 1000)

    return {
        "sample_rate": sample_rate,
        "channels": channels,
        "sample_width_bits": sample_width * 8,
        "duration_ms": duration_ms,
    }
