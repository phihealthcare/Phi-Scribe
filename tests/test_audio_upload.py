from app.routes.audio import (
    ALLOWED_EXTENSIONS,
    EXTENSIONS_REQUIRING_EXTRACT,
    _allowed_file,
    _prepare_transcription_audio,
)


def test_allowed_file_accepts_mp4() -> None:
    assert "mp4" in ALLOWED_EXTENSIONS
    assert _allowed_file("consulta-real-1.mp4")
    assert _allowed_file("clip.MP4")
    assert not _allowed_file("video.avi")


def test_mp4_requires_extract() -> None:
    assert "mp4" in EXTENSIONS_REQUIRING_EXTRACT
    assert "mp3" not in EXTENSIONS_REQUIRING_EXTRACT


def test_prepare_transcription_audio_passthrough_wav(tmp_path) -> None:
    wav_path = tmp_path / "sample.wav"
    wav_path.write_bytes(b"RIFF")
    prepared, temp = _prepare_transcription_audio(wav_path)
    assert prepared == wav_path
    assert temp is None
