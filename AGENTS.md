# Repository guidance

## Project

AI Karaoke Studio is a local Python application for generating Russian/Cyrillic
karaoke videos. It combines Demucs stem separation, Whisper transcription,
optional Wav2Vec2 CTC alignment, editable lyrics/timings, and FFmpeg rendering.
The primary platform is macOS on Apple Silicon; preserve existing CPU fallbacks.

## Setup and commands

- Use Python 3.11 (see `.python-version`); supported versions are >=3.10,<3.12.
- Manage dependencies with `uv` and keep `pyproject.toml` and `uv.lock` in sync
  when changing dependencies. If `uv` is not on PATH, try `~/.local/bin/uv`.
- Install/sync the environment: `uv sync`.
- Launch the Gradio UI: `uv run karaoke-ui` or `uv run python run_ui.py`.
  The default address is `http://127.0.0.1:7860`.
- Run the CLI directly: `uv run python -m karaoke.cli song.mp3`.
  Inspect `--help` for current options. The packaged `uv run karaoke` command
  targets `karaoke.cli:main`.
- Media processing requires FFmpeg with the `subtitles` filter (libass).
  The code prefers Homebrew `ffmpeg-full`; some tests invoke `ffmpeg` on PATH.
  YouTube downloads use yt-dlp and Node.js. Model inference may download weights
  on first use.

## Code map

- `src/karaoke/cli.py`: shared pipeline orchestration. `analyze_and_transcribe`
  creates reusable state; `render_from_state` rebuilds from edited state.
- `src/karaoke/app_ui.py`: Gradio UI, embedded JavaScript/CSS, timeline editing,
  playback, and UI-to-Python state synchronization.
- `src/karaoke/downloader.py`: local/URL media input, cookies, cover extraction.
- `src/karaoke/separator.py` and `transcriber.py`: model loading and inference.
- `src/karaoke/aligner.py`: word timing, Russian line splitting, editor conversion.
- `src/karaoke/mixer.py`: guide vocals, waveform peaks, automation, FX detection.
- `src/karaoke/ass_writer.py`: ASS subtitles, line layout, highlighting, visual FX.
- `src/karaoke/emoji_layer.py`: Apple Color Emoji sprites and ASS placeholders.
- `src/karaoke/video.py`: backgrounds, compositing, FFmpeg encoding.
- `src/karaoke/cancel_manager.py`: cancellation flags, streaming subprocess output,
  and child-process lifecycle. Progress callbacks must run on the calling thread.
- `src/karaoke/render_progress.py`: FFmpeg progress, ETA, and output-size guard.
- `src/karaoke/media.py`: ffprobe stream/duration inspection.
- `tests/test_karaoke.py`: regression tests and a standalone test runner.

## Implementation conventions

- Follow the existing four-space Python style, snake_case functions, type hints,
  and `pathlib.Path` usage. There is no configured formatter or linter.
- Preserve Russian user-facing text and UTF-8/Cyrillic handling. Keep JSON output
  readable with `ensure_ascii=False` where the existing pipeline uses it.
- Preserve word dictionaries (`text`, `start`, `end`, and optional `syllables`),
  editor timestamp syntax, and saved-state compatibility across analysis,
  editing, mixing, subtitle generation, and rendering.
- Keep rebuilding independent of model inference; reuse saved stems and state.
- When changing timeline payloads, update the Python callbacks and embedded
  JavaScript together. Preserve vocal/FX interval persistence during rebuilds.
- Use the cancellation manager for long-running child processes and retain
  cancellation checks in pipeline stages.
- Keep emoji placeholder widths and rendered sprite positioning consistent.
  Native emoji rendering depends on macOS fonts; account for this in validation.
- Keep changes focused. Do not commit generated media, model files, browser
  cookies, `.venv`, or generated `output`/`separated` directories.

## Validation

- Run focused regressions first, for example:
  `uv run --with pytest python -m pytest tests/test_karaoke.py -k lyrics_editor_roundtrip`.
- Run the full suite when changing shared pipeline/rendering behavior:
  `uv run --with pytest python -m pytest tests`.
  Pytest is not declared in the project dependencies; `--with pytest` supplies it.
- Alternatively, the existing standalone runner is:
  `uv run python tests/test_karaoke.py`.
- Rendering tests create real audio/video and require FFmpeg; emoji tests use
  Apple fonts, and downloader configuration tests require Node.js. Report
  missing prerequisites separately from regressions. Avoid full model inference
  for routine validation when synthetic fixtures cover the behavior.
- For UI changes, exercise the affected editing/playback/rebuild flow in the
  browser. For subtitle/FX changes, inspect a short rendered sample as well as
  generated ASS/state data.
