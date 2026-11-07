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
