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


def concat_wavs(wav_paths: list[Path], output_path: Path) -> Path:
    """Concatenate WAV files that all share the same format (sample rate,
    channels, sample width) by appending raw PCM frames — no re-encoding, so
    this is lossless. Callers must normalize each input first (normalize_audio
    always produces the same canonical format), otherwise the frames won't
    line up and the result will play back distorted/at the wrong speed."""
    if not wav_paths:
        raise ValueError("concat_wavs requires at least one input path")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(wav_paths[0]), "rb") as first:
        params = first.getparams()

    with wave.open(str(output_path), "wb") as out:
        out.setparams(params)
        for path in wav_paths:
            with wave.open(str(path), "rb") as segment:
                segment_params = segment.getparams()
                if (
                    segment_params.nchannels != params.nchannels
                    or segment_params.framerate != params.framerate
                    or segment_params.sampwidth != params.sampwidth
                ):
                    raise ValueError(
                        f"concat_wavs: format mismatch in {path} "
                        f"(expected {params.nchannels}ch/{params.framerate}Hz/{params.sampwidth * 8}bit, "
                        f"got {segment_params.nchannels}ch/{segment_params.framerate}Hz/{segment_params.sampwidth * 8}bit)"
                    )
                out.writeframes(segment.readframes(segment.getnframes()))

    return output_path


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
