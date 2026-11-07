#!/usr/bin/env python3
"""
Model Context Protocol (MCP) Server for AI Karaoke Studio.

Enables autonomous AI agents (Claude Desktop, Antigravity, Cursor, Cline, etc.) to:
- Inspect and manage karaoke projects
- Autonomously trigger transcription, separation (Demucs), and vocal alignment
- Read and edit lyrics timestamps and syllabic rhythms
- Tweak models, VAD filters, CTC Wav2Vec2 alignment, and chorus repeats
- Re-render Full HD 1080p karaoke videos with custom visual effects and styles
- Check hardware profiles and AI model statuses
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.mcpserver import MCPServer

from karaoke.aligner import (
    editor_text_to_lines,
    lines_to_editor_text,
    validate_karaoke_lines,
    regroup_editor_lines,
    split_long_editor_lines,
)
from karaoke.cli import analyze_and_transcribe, render_from_state
from karaoke.hardware import get_hardware_profile_dict
from karaoke.model_manager import get_models_status_list
from karaoke.slice_editor import align_audio_slice, apply_slice_to_project

# Repo paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = (ROOT_DIR / "output").resolve()
WORK_DIR = (OUTPUT_DIR / "work").resolve()

# Create MCP server instance
server = MCPServer("karaoke-studio")


@server.tool()
def list_projects() -> List[Dict[str, Any]]:
    """List all available karaoke projects in AI Karaoke Studio with their status, video availability, and modification time."""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    state_files = sorted(
        WORK_DIR.glob("*_state.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    result = []
    for f in state_files:
        title = f.stem.replace("_state", "")
        mtime = f.stat().st_mtime
        video_file = OUTPUT_DIR / f"{title}_karaoke.mp4"
        cover_file = WORK_DIR / f"{title}_cover.png"

        dur = 0.0
        lines_count = 0
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            dur = float(data.get("duration", 0.0))
            lines_count = len(data.get("lines", []))
        except Exception:
            pass

        result.append({
            "title": title,
            "duration": round(dur, 2),
            "lines_count": lines_count,
            "has_video": video_file.exists(),
            "has_cover": cover_file.exists(),
            "video_path": str(video_file) if video_file.exists() else None,
            "mtime": mtime,
        })
    return result


@server.tool()
def get_project(title: str) -> Dict[str, Any]:
    """Retrieve full project state including lyrics with timestamps, model parameters, and media paths.

    Args:
        title: The project title / ID.
    """
    state_file = WORK_DIR / f"{title}_state.json"
    if not state_file.exists():
        return {"error": f"Проект '{title}' не найден в {WORK_DIR}"}

    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"Ошибка чтения state.json: {e}"}

    video_file = OUTPUT_DIR / f"{title}_karaoke.mp4"
    lyrics_txt = OUTPUT_DIR / f"{title}_lyrics.txt"

    return {
        "title": title,
        "duration": round(float(data.get("duration", 0.0)), 2),
        "lines_count": len(data.get("lines", [])),
        "editor_text": data.get("editor_text", ""),
        "reference_lyrics": data.get("reference_lyrics", ""),
        "generation_params": data.get("generation_params", {}),
        "has_video": video_file.exists(),
        "video_path": str(video_file) if video_file.exists() else None,
        "lyrics_file": str(lyrics_txt) if lyrics_txt.exists() else None,
        "vocals_wav": data.get("vocals_wav"),
        "no_vocals_wav": data.get("no_vocals_wav"),
    }


@server.tool()
def generate_karaoke(
    source: str,
    reference_lyrics: str = "",
    model_size: str = "large-v3-turbo",
    demucs_model: str = "htdemucs_ft",
    vad: str = "auditok",
    use_ctc_align: bool = True,
    use_video_bg: bool = False,
    vocal_volume_pct: float = 0.0,
    num_lines: int = 4,
    video_quality: str = "balanced",
) -> Dict[str, Any]:
    """Generate a new karaoke video from scratch (audio/video file or YouTube URL).

    Args:
        source: Local audio/video file path OR YouTube URL or search query ('ytsearch1:...').
        reference_lyrics: Optional official text of the song lyrics to align with.
        model_size: Whisper speech recognition model ('large-v3-turbo', 'bond005/whisper-podlodka-turbo', 'large-v3', etc.).
        demucs_model: Demucs stem separation model ('htdemucs_ft', 'htdemucs', 'mdx_extra').
        vad: Voice activity filter ('auditok', 'silero', or 'none'). 'auditok' is recommended.
        use_ctc_align: Whether to use Wav2Vec2 Russian forced alignment for precise syllable timing.
        use_video_bg: Whether to keep original video background if source is a video.
        vocal_volume_pct: Volume of original vocal guide in backing track (0 = pure instrumental, 10-15 = subtle guide).
        num_lines: Number of teleprompter lines displayed simultaneously (3 or 4).
        video_quality: FFmpeg encoding preset ('fast', 'balanced', 'high').
    """
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        WORK_DIR.mkdir(parents=True, exist_ok=True)

        vocal_vol = float(vocal_volume_pct) / 100.0

        state_data = analyze_and_transcribe(
            source=source,
            output_dir=OUTPUT_DIR,
            model_size=model_size,
            demucs_model=demucs_model,
            language="ru",
            reference_lyrics=reference_lyrics.strip(),
            use_ctc_align=use_ctc_align,
            download_video=use_video_bg,
            condition_on_previous_text=False,
            vad=vad if vad.lower() != "none" else None,
            strict_repeats=False,
        )

        title = state_data["title"]
        bg_param = Path(state_data["custom_bg"]) if state_data.get("custom_bg") else None
        use_cov = False if bg_param else (not use_video_bg)

        final_video, _, updated_editor_text = render_from_state(
            state_data=state_data,
            output_dir=OUTPUT_DIR,
            editor_text=state_data.get("editor_text"),
            vocal_volume=vocal_vol,
            num_lines=num_lines,
            video_quality=video_quality,
            background=bg_param,
            use_cover_bg=use_cov,
            use_video_bg=use_video_bg if not bg_param else False,
        )

        return {
            "status": "success",
            "title": title,
            "duration": round(float(state_data.get("duration", 0.0)), 2),
            "lines_count": len(state_data.get("lines", [])),
            "video_path": str(final_video),
            "editor_text": updated_editor_text,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@server.tool()
def regenerate_project(
    title: str,
    reference_lyrics: Optional[str] = None,
    model_size: str = "large-v3-turbo",
    demucs_model: str = "htdemucs_ft",
    vad: str = "auditok",
    use_ctc_align: bool = True,
    vocal_volume_pct: float = 0.0,
    num_lines: int = 4,
    video_quality: str = "balanced",
) -> Dict[str, Any]:
    """Re-generate an existing project with adjusted AI parameters without re-uploading the audio file.
    Re-uses cached Demucs stems when the model name matches, accelerating re-alignment to seconds.

    Args:
        title: Project title.
        reference_lyrics: Optional updated lyrics text (if omitted, uses previously saved lyrics).
        model_size: Whisper model.
        demucs_model: Demucs model.
        vad: VAD filter ('auditok', 'silero', 'none').
        use_ctc_align: Wav2Vec2 CTC alignment flag.
        vocal_volume_pct: Guide vocal volume percentage (0-100).
        num_lines: 3 or 4 lines.
        video_quality: Video quality preset.
    """
    state_file = WORK_DIR / f"{title}_state.json"
    if not state_file.exists():
        return {"status": "error", "error": f"Проект '{title}' не найден."}

    try:
        existing_state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as e:
        return {"status": "error", "error": f"Не удалось прочитать state: {e}"}

    # Find source audio
    candidates = [
        existing_state.get("source_audio"),
        WORK_DIR / f"{title}_source.wav",
        WORK_DIR / f"{title}_source.mp3",
        WORK_DIR / f"{title}.wav",
        existing_state.get("video_bg"),
    ]
    source_path = None
    for cand in candidates:
        if cand and Path(cand).exists():
            source_path = str(Path(cand).resolve())
            break

    if not source_path:
        voc = existing_state.get("vocals_wav")
        inst = existing_state.get("no_vocals_wav")
        if voc and inst and Path(voc).exists() and Path(inst).exists():
            recon_wav = WORK_DIR / f"{title}_source.wav"
            ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
            subprocess.run([
                ffmpeg_bin, "-y",
                "-i", str(voc),
                "-i", str(inst),
                "-filter_complex", "amix=inputs=2:duration=first:dropout_transition=0",
                "-c:a", "pcm_s16le",
                str(recon_wav)
            ], check=True, capture_output=True)
            if recon_wav.exists():
                source_path = str(recon_wav)

    if not source_path:
        return {"status": "error", "error": "Не удалось найти аудиофайл существующего проекта для перегенерации."}

    lyrics_to_use = reference_lyrics if reference_lyrics is not None else existing_state.get("reference_lyrics", "")

    return generate_karaoke(
        source=source_path,
        reference_lyrics=lyrics_to_use,
        model_size=model_size,
        demucs_model=demucs_model,
        vad=vad,
        use_ctc_align=use_ctc_align,
        use_video_bg=bool(existing_state.get("video_bg")),
        vocal_volume_pct=vocal_volume_pct,
        num_lines=num_lines,
        video_quality=video_quality,
    )


@server.tool()
def update_project_lyrics(title: str, editor_text: str) -> Dict[str, Any]:
    """Update lyrics lines and timestamps for a project.

    Args:
        title: Project title.
        editor_text: Text formatted with timestamps: '[MM:SS.cs -> MM:SS.cs] Текст строки\\n...'
    """
    state_file = WORK_DIR / f"{title}_state.json"
    if not state_file.exists():
        return {"status": "error", "error": f"Проект '{title}' не найден."}

    try:
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
        lines = editor_text_to_lines(editor_text, state_data.get("lines"))
        validate_karaoke_lines(lines)

        clean_editor = lines_to_editor_text(lines)
        state_data["lines"] = lines
        state_data["editor_text"] = clean_editor
        state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

        # Save lyrics.txt
        lyrics_txt = OUTPUT_DIR / f"{title}_lyrics.txt"
        lyrics_txt.write_text(clean_editor, encoding="utf-8")

        return {
            "status": "success",
            "title": title,
            "lines_count": len(lines),
            "editor_text": clean_editor,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@server.tool()
def shift_line_timing(title: str, line_index: int, new_start: float, new_end: float) -> Dict[str, Any]:
    """Shift or stretch/compress the timing window of a specific line in a project.

    Args:
        title: Project title.
        line_index: 0-based index of the line.
        new_start: New start time in seconds (e.g. 15.20).
        new_end: New end time in seconds (e.g. 19.50).
    """
    state_file = WORK_DIR / f"{title}_state.json"
    if not state_file.exists():
        return {"status": "error", "error": f"Проект '{title}' не найден."}

    try:
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
        lines = state_data.get("lines", [])
        if line_index < 0 or line_index >= len(lines):
            return {"status": "error", "error": f"Неверный индекс строки {line_index}. Всего строк: {len(lines)}"}

        line = lines[line_index]
        new_start = max(0.0, round(new_start, 2))
        new_end = max(new_start + 0.15, round(new_end, 2))

        if isinstance(line, list) and line:
            old_start = float(line[0].get("start", 0.0))
            old_end = float(line[-1].get("end", old_start + 1.0))
            old_dur = max(0.01, old_end - old_start)
            new_dur = new_end - new_start

            for w in line:
                rel_s = (float(w.get("start", old_start)) - old_start) / old_dur
                rel_e = (float(w.get("end", old_end)) - old_start) / old_dur
                w["start"] = round(new_start + rel_s * new_dur, 2)
                w["end"] = round(new_start + rel_e * new_dur, 2)
        elif isinstance(line, dict):
            line["start"] = new_start
            line["end"] = new_end

        validate_karaoke_lines(lines)
        clean_editor = lines_to_editor_text(lines)
        state_data["lines"] = lines
        state_data["editor_text"] = clean_editor
        state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "status": "success",
            "title": title,
            "line_index": line_index,
            "new_start": new_start,
            "new_end": new_end,
            "line_text": clean_editor.splitlines()[line_index],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@server.tool()
def rebuild_video(
    title: str,
    visual_effects: str = "sparkles_pulse",
    highlight_color: str = "gold_neon",
    vocal_volume_pct: float = 0.0,
    num_lines: int = 4,
    video_quality: str = "balanced",
    watermark_text: str = "",
    dual_audio_mp4: bool = True,
) -> Dict[str, Any]:
    """Re-render the final Full HD 1080p MP4 karaoke video using current lyrics, timings, and custom styling.

    Args:
        title: Project title.
        visual_effects: Visual particles FX ('sparkles_pulse', 'neon_matrix', 'fire_particles', 'none').
        highlight_color: Teleprompter color ('gold_neon', 'cyan', 'magenta', 'lime', 'white').
        vocal_volume_pct: Guide vocal volume percentage (0-100).
        num_lines: Number of lines on screen (3 or 4).
        video_quality: FFmpeg encoding preset ('fast', 'balanced', 'high').
        watermark_text: Optional watermark text in top corner.
        dual_audio_mp4: Whether to include dual audio tracks (Track 1 = Backing, Track 2 = Original Vocals).
    """
    state_file = WORK_DIR / f"{title}_state.json"
    if not state_file.exists():
        return {"status": "error", "error": f"Проект '{title}' не найден."}

    try:
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
        vocal_vol = float(vocal_volume_pct) / 100.0

        bg_param = Path(state_data["custom_bg"]) if state_data.get("custom_bg") else None
        use_cov = False if bg_param else (not bool(state_data.get("video_bg")))
        use_vid = bool(state_data.get("video_bg")) if not bg_param else False

        final_video, _, _ = render_from_state(
            state_data=state_data,
            output_dir=OUTPUT_DIR,
            editor_text=state_data.get("editor_text"),
            vocal_volume=vocal_vol,
            num_lines=num_lines,
            video_quality=video_quality,
            background=bg_param,
            use_cover_bg=use_cov,
            use_video_bg=use_vid,
            visual_effects=visual_effects,
            highlight_color=highlight_color,
            dual_audio_mp4=dual_audio_mp4,
            watermark_text=watermark_text if watermark_text else None,
        )

        return {
            "status": "success",
            "title": title,
            "video_path": str(final_video),
            "video_size_mb": round(final_video.stat().st_size / (1024 * 1024), 2) if final_video.exists() else 0.0,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@server.tool()
def align_slice(title: str, start: float, end: float, text: str, mode: str = "syllables_rms") -> Dict[str, Any]:
    """Perform surgical word-level alignment on a short time window using isolated vocal energy.

    Args:
        title: Project title.
        start: Start time in seconds.
        end: End time in seconds.
        text: Target text to align within this audio slice.
        mode: Alignment algorithm ('syllables_rms' or 'ctc').
    """
    state_file = WORK_DIR / f"{title}_state.json"
    if not state_file.exists():
        return {"status": "error", "error": f"Проект '{title}' не найден."}

    try:
        res = align_audio_slice(title=title, start=start, end=end, text=text, mode=mode)
        return res
    except Exception as e:
        return {"status": "error", "error": str(e)}


@server.tool()
def get_hardware_profile() -> Dict[str, Any]:
    """Get system hardware capabilities: GPU type (CUDA, Apple Silicon MPS, CPU), VRAM, and recommended AI models."""
    return get_hardware_profile_dict()


@server.tool()
def get_models_catalog() -> Dict[str, Any]:
    """Get status of installed and available Whisper and Demucs AI models with disk sizes."""
    return {"models": get_models_status_list()}


def main():
    """Run the MCP server over stdio."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
