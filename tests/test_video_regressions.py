"""Real FFmpeg regressions: finite output, correct sound, and safe rebuilds."""
import os
import signal
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from karaoke import video
from karaoke.ass_writer import generate_ass_from_lines
from karaoke.cancel_manager import GenerationCancelledError, reset_cancel
from karaoke.downloader import get_audio_from_source
from karaoke.media import probe_media, video_streams


@pytest.fixture
def media(tmp_path):
    reset_cancel()
    audio = tmp_path / "mix.wav"
    sr = 44100
    sf.write(audio, 0.3 * np.sin(2 * np.pi * 880 * np.arange(sr * 2) / sr), sr)
    ass = tmp_path / "lyrics.ass"
    generate_ass_from_lines(
        [[{"text": "Проверка", "start": 0.5, "end": 1.5}]], ass,
        visual_effects="none", fx_intervals=[],
    )
    return audio, ass


@pytest.mark.parametrize("source_audio,emoji,duration", [
    (True, False, 0.7), (True, True, 3),
    (False, False, 3), (False, True, 0.7),
])
def test_video_render_is_bounded_and_uses_mix(tmp_path, media, source_audio, emoji, duration):
    audio, ass = media
    source = tmp_path / "source.m4v"
    cmd = [video.find_ffmpeg(), "-y", "-f", "lavfi", "-i",
           f"testsrc2=size=320x180:rate=10:duration={duration}"]
    if source_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=15)
    concat = None
    if emoji:
        from PIL import Image
        frame = tmp_path / "transparent.png"
        Image.new("RGBA", (1920, 1080), (0, 0, 0, 0)).save(frame)
        concat = tmp_path / "lyrics.ffconcat"
        concat.write_text(f"ffconcat version 1.0\nfile '{frame}'\nduration 2\nfile '{frame}'\n")
    output = tmp_path / "result.mp4"
    # Kill the whole renderer process group on timeout, including FFmpeg.
    script = """
import sys
from pathlib import Path
from karaoke.video import render_karaoke_video
audio, ass, source, output, concat = sys.argv[1:]
render_karaoke_video(Path(audio), Path(ass), Path(output), background=Path(source),
                    use_hardware_accel=False, video_quality='light', fps=10,
                    lyric_emoji_concat=Path(concat) if concat else None)
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(audio), str(ass), str(source), str(output),
         str(concat) if concat else ""],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=40)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        pytest.fail("Video render did not terminate within 40 seconds")
    assert proc.returncode == 0, (stdout + stderr).decode(errors="replace")
    metadata = probe_media(output, video.find_ffmpeg())
    assert abs(float(metadata["format"]["duration"]) - 2) < 0.15
    assert len(metadata["streams"]) == 2
    assert len(video_streams(metadata)) == 1
    assert output.stat().st_size < 2_000_000
    decoded = subprocess.run(
        [video.find_ffmpeg(), "-v", "error", "-i", str(output), "-vn", "-f", "f32le",
         "-ac", "1", "-ar", "44100", "pipe:1"], capture_output=True, check=True, timeout=10,
    )
    samples = np.frombuffer(decoded.stdout, dtype=np.float32)
    frequencies = np.fft.rfftfreq(len(samples), 1 / 44100)
    peak = frequencies[np.argmax(np.abs(np.fft.rfft(samples)))]
    assert abs(peak - 880) < 5, f"Original video sound leaked into mix: {peak} Hz"
    assert not list(tmp_path.glob(".result-*.mp4"))


@pytest.mark.parametrize("cancelled", [False, True])
def test_failed_rebuild_preserves_previous_video(tmp_path, media, monkeypatch, cancelled):
    audio, ass = media
    output = tmp_path / "result.mp4"
    output.write_bytes(b"previous successful render")

    def fail(cmd, prefix, **kwargs):
        Path(cmd[-1]).write_bytes(b"partial render")
        if cancelled:
            raise GenerationCancelledError("cancelled")
        raise subprocess.CalledProcessError(1, cmd, stderr=b"encoder error")

    monkeypatch.setattr(video, "run_cancellable_command", fail)
    with pytest.raises(GenerationCancelledError if cancelled else RuntimeError):
        video.render_karaoke_video(audio, ass, output, use_hardware_accel=False)
    assert output.read_bytes() == b"previous successful render"
    assert not list(tmp_path.glob(".result-*.mp4"))


def test_silent_video_source_rejected_before_analysis(tmp_path):
    source = tmp_path / "silent.mp4"
    subprocess.run([video.find_ffmpeg(), "-y", "-f", "lavfi", "-i",
                    "color=size=64x64:duration=0.2", "-c:v", "libx264", str(source)],
                   check=True, capture_output=True, timeout=10)
    reset_cancel()
    with pytest.raises(ValueError, match="нет аудиодорожки"):
        get_audio_from_source(str(source), tmp_path / "work")


def test_saved_video_background_used_when_youtube_checkbox_off(tmp_path, media, monkeypatch):
    from karaoke import cli
    audio, _ = media
    source = tmp_path / "saved.mp4"
    source.touch()
    captured = []
    monkeypatch.setattr(cli, "render_karaoke_video", lambda **kwargs: captured.append(kwargs))
    monkeypatch.setattr(cli, "ensure_project_cover", lambda *args: None)
    state = {"title": "saved", "vocals_wav": str(audio), "no_vocals_wav": str(audio),
             "video_bg": str(source), "duration": 2, "lines": [], "fx_intervals": []}
    reset_cancel()
    cli.render_from_state(state, tmp_path, use_video_bg=False)
    assert captured[-1]["background"] == source
    source.unlink()
    with pytest.raises(FileNotFoundError, match="Выберите замену"):
        cli.render_from_state(state, tmp_path, use_video_bg=False)


def test_hardware_failure_retries_with_bounded_software_render(tmp_path, media, monkeypatch):
    audio, ass = media
    output = tmp_path / "fallback.mp4"
    real_run = video.run_cancellable_command
    calls = []

    def run(cmd, prefix, **kwargs):
        calls.append(cmd)
        if "h264_videotoolbox" in cmd:
            Path(cmd[-1]).write_bytes(b"partial hardware render")
            raise subprocess.CalledProcessError(1, cmd, stderr=b"hardware unavailable")
        real_run(cmd, prefix, **kwargs)

    monkeypatch.setattr(video, "run_cancellable_command", run)
    video.render_karaoke_video(audio, ass, output, fps=10, video_quality="light")
    assert len(calls) == 2
    assert abs(float(probe_media(output, video.find_ffmpeg())["format"]["duration"]) - 2) < 0.15
    assert not list(tmp_path.glob(".fallback-*.mp4"))


def test_uploaded_video_survives_temporary_upload_cleanup(tmp_path, media, monkeypatch):
    from karaoke import cli
    audio, _ = media
    upload = tmp_path / "uploads" / "clip.mp4"
    upload.parent.mkdir()
    upload.write_bytes(b"original video bytes")
    output = tmp_path / "project"
    monkeypatch.setattr(cli, "get_audio_from_source", lambda *args, **kwargs: (audio, "clip", None, upload))
    monkeypatch.setattr(cli, "ensure_project_cover", lambda *args: None)
    monkeypatch.setattr(cli, "separate_stems", lambda **kwargs: (audio, audio))
    monkeypatch.setattr(cli, "transcribe_vocals", lambda **kwargs: {"segments": []})
    monkeypatch.setattr(cli, "detect_chorus_fx_intervals", lambda *args: [])
    reset_cancel()
    state = cli.analyze_and_transcribe(str(upload), output)
    stored = Path(state["video_bg"])
    assert stored != upload
    assert state["use_video_bg"] is True
    repeated = cli.analyze_and_transcribe(str(upload), output)
    assert repeated["video_bg"] == state["video_bg"]
    assert len(list(stored.parent.iterdir())) == 1
    upload.unlink()
    assert stored.read_bytes() == b"original video bytes"


def test_download_uses_its_own_mkv_and_never_unrelated_video(tmp_path, media, monkeypatch):
    from karaoke import downloader
    source = tmp_path / "download.mkv"
    subprocess.run([video.find_ffmpeg(), "-y", "-f", "lavfi", "-i",
                    "color=size=64x64:duration=0.2", "-i", str(media[0]),
                    "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source)],
                   check=True, capture_output=True, timeout=10)
    unrelated = tmp_path / "other_raw.mp4"
    unrelated.write_bytes(b"another project")

    class Download:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, *args, **kwargs):
            return {"title": "download", "filepath": str(source)}

        def prepare_filename(self, info):
            return str(source)

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", Download)
    reset_cancel()
    audio, _, _, background = downloader.get_audio_from_source(
        "https://example.invalid/video", tmp_path, download_video=True, cookies_browser=None,
    )
    assert background.suffix == ".mkv"
    assert audio.is_file()
    assert unrelated.read_bytes() == b"another project"


def test_analyze_and_transcribe_with_reference_lyrics(tmp_path, monkeypatch):
    from karaoke import cli
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF" + b"\x00" * 40)
    output = tmp_path / "project"

    monkeypatch.setattr(cli, "get_audio_from_source", lambda *args, **kwargs: (audio, "song", None, None))
    monkeypatch.setattr(cli, "ensure_project_cover", lambda *args: None)
    monkeypatch.setattr(cli, "separate_stems", lambda **kwargs: (audio, audio))
    monkeypatch.setattr(cli, "transcribe_vocals", lambda **kwargs: {
        "segments": [{"words": [{"text": "тест", "start": 1.0, "end": 2.0}]}]
    })
    monkeypatch.setattr(cli, "detect_chorus_fx_intervals", lambda *args: [])
    monkeypatch.setattr(cli, "compute_waveform_peaks", lambda *args: ([0.1] * 10, 2.0))

    passed_model = None
    def mock_refine(raw_words, reference_lyrics, vocals_path, whisper_model, work_dir):
        nonlocal passed_model
        passed_model = whisper_model
        return raw_words

    monkeypatch.setattr(cli, "refine_unaligned_vocal_slices", mock_refine)

    state = cli.analyze_and_transcribe(
        str(audio),
        output,
        model_size="bond005/whisper-podlodka-turbo",
        reference_lyrics="тест эталона",
    )
    assert passed_model == "bond005/whisper-podlodka-turbo"
    assert "editor_text" in state

