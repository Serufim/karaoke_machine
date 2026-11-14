---
name: karaoke-automation
description: >-
  Use this skill when the user asks to generate karaoke videos, inspect karaoke projects,
  adjust lyrics or syllable timings, rebuild karaoke videos, or query AI Karaoke Studio MCP tools.
---

# Karaoke Automation Skill

This skill guides Antigravity agents in controlling AI Karaoke Studio via its native MCP tools (`karaoke-studio`).

## Available MCP Tools

* **`list_projects`**: Lists all existing karaoke projects in `output/` with their audio status, subtitle presence, and video rendering status.
* **`get_project`**: Retrieves complete project state for `project_id`, including full reference lyrics, word-by-word timestamps, audio files, and style configuration.
* **`generate_karaoke`**: Fully autonomous end-to-end karaoke creation from a local audio file or YouTube URL:
  * Arguments: `media_path` (required), `reference_lyrics` (optional text), `whisper_model`, `demucs_model`, `use_ctc_align`, `vad_filter`, `bg_mode`.
* **`regenerate_project`**: Re-runs transcription or alignment with altered model settings while reusing Demucs stem cache.
* **`get_lines`**: Returns word-level and syllable-level timings of lines overlapping `[start_time, end_time]`, plus raw Whisper words in that window.
* **`analyze_vocal_window`**: Returns the isolated-vocal loudness profile (` .:|#`), detected pauses, and syllable onsets in `[start_time, end_time]`.
* **`set_line_timing`**: Moves/stretches one line to `[new_start, new_end]` (trimming neighbours on overlap) and optionally re-aligns its words/syllables to the vocal (`realign_by_vocals=True`).
* **`set_word_timings`**: Sets exact `start`/`end` (and optional `syllables`) for every word of a single line.
* **`shift_lines`**: Shifts a range of consecutive lines `[from_index..to_index]` by `delta_seconds` while preserving internal word & syllable intervals.
* **`realign_lines`**: Re-generates timings of specific lines (`line_indices`) using `mode="vocals"` (MMS_FA CTC forced alignment on vocals) or `mode="whisper"` (raw Whisper word anchors).
* **`list_timing_history`** / **`restore_timing_snapshot`**: Lists or restores saved timing snapshots (`output/work/<title>_history/`).
* **`shift_line_timing`**: Shifts start/end time of a specific line by `shift_seconds` (positive or negative).
* **`update_project_lyrics`**: Updates line text or timing directly in `karaoke_state.json`.
* **`rebuild_video`**: Re-renders ASS subtitles and Full HD MP4 video with updated timings or visual styles (`cyberpunk`, `gold_neon`, `silver`, `cover_blur`).
* **`get_hardware_profile`**: Inspects available GPUs (Apple Silicon Metal/MPS or NVIDIA CUDA) and memory to recommend optimal models.

## Common Workflows

### 1. Generating a New Karaoke Track
1. Call `get_hardware_profile` to choose the best model for the machine.
2. Call `generate_karaoke(media_path="...", reference_lyrics="...", use_ctc_align=True)`.
3. Inform the user of the output path and project ID.

### 2. Inspecting and Adjusting Timings
1. Call `get_project(project_id="...")` to inspect existing lines and timestamps.
2. Identify any lines with misalignments.
3. Call `shift_line_timing(project_id="...", line_index=N, shift_seconds=delta)`.
4. Call `rebuild_video(project_id="...")` to generate the new video without re-running Demucs or Whisper.
