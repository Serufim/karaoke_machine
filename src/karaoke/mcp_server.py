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
import urllib.request
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


def notify_studio_ui(event_type: str, title: str, message: str = "", action: str = ""):
    """Broadcasts event to running studio UI via local HTTP endpoint across possible ports."""
    payload = json.dumps({
        "type": event_type,
        "title": title,
        "message": message,
        "action": action,
    }).encode("utf-8")
    for port in (7860, 7861, 7862, 7863, 7864, 7865):
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/system/notify-update",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    break
        except Exception:
            continue



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

        notify_studio_ui("project_updated", title, "Текст обновлен через MCP", "lyrics_updated")

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

        notify_studio_ui("project_updated", title, "Тайминг сдвинут через MCP", "timing_shifted")

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

        state_data["visual_effects"] = visual_effects
        state_data["highlight_color"] = highlight_color
        state_data["num_lines"] = num_lines
        state_data["has_video"] = True
        state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

        notify_studio_ui("completed", title, "Видео успешно пересобрано через MCP!", "rebuild")

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


# ---------------------------------------------------------------------------
# Fine-grained timing tools (inspect / move / re-align individual lines)
# ---------------------------------------------------------------------------


def _load_state(title: str) -> Dict[str, Any]:
    state_file = WORK_DIR / f"{title}_state.json"
    if not state_file.exists():
        raise FileNotFoundError(f"Проект '{title}' не найден.")
    return json.loads(state_file.read_text(encoding="utf-8"))


def _save_state(title: str, state_data: Dict[str, Any], snapshot_reason: Optional[str], prev_state: Optional[Dict[str, Any]] = None) -> None:
    from karaoke import timing_history

    if snapshot_reason and prev_state is not None:
        timing_history.save_snapshot(WORK_DIR, title, prev_state, reason=snapshot_reason)
    lines = state_data.get("lines") or []
    validate_karaoke_lines(lines)
    state_data["editor_text"] = lines_to_editor_text(lines)
    state_data["line_marks"] = timing_history.refresh_mark_timings(lines, state_data.get("line_marks"))
    try:
        from karaoke.alignment_qa import evaluate_alignment_quality

        vocals = Path(state_data["vocals_wav"]) if state_data.get("vocals_wav") else None
        state_data["alignment_report"] = evaluate_alignment_quality(lines, vocals)
    except Exception:
        pass
    (WORK_DIR / f"{title}_state.json").write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")


def _fmt_line(idx: int, line: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "index": idx,
        "start": round(float(line[0]["start"]), 2) if line else None,
        "end": round(float(line[-1]["end"]), 2) if line else None,
        "text": " ".join(str(w.get("text", "")) for w in line),
        "words": [
            {
                "text": w.get("text"),
                "start": round(float(w["start"]), 2),
                "end": round(float(w["end"]), 2),
                **(
                    {"syllables": [
                        {"text": t.get("text"), "start": round(float(t["start"]), 2), "end": round(float(t["end"]), 2)}
                        for t in w.get("syllable_timings", [])
                    ]}
                    if w.get("syllable_timings") else {}
                ),
            }
            for w in line
        ],
    }


@server.tool()
def get_lines(title: str, start_time: float = 0.0, end_time: float = 1e9) -> Dict[str, Any]:
    """Return word-level (and syllable-level) timings of lines overlapping [start_time, end_time], plus raw Whisper words there.

    Args:
        title: Project title.
        start_time: Window start in seconds.
        end_time: Window end in seconds.
    """
    try:
        s = _load_state(title)
    except Exception as e:
        return {"status": "error", "error": str(e)}
    lines = s.get("lines") or []
    picked = [
        _fmt_line(i, ln) for i, ln in enumerate(lines)
        if ln and float(ln[-1]["end"]) >= start_time and float(ln[0]["start"]) <= end_time
    ]
    whisper = [
        {"text": w.get("text"), "start": round(float(w["start"]), 2), "end": round(float(w["end"]), 2)}
        for w in (s.get("recognized_words") or [])
        if float(w.get("end", 0)) >= start_time and float(w.get("start", 0)) <= end_time
    ]
    return {"status": "success", "lines": picked, "whisper_words": whisper}


@server.tool()
def analyze_vocal_window(title: str, start_time: float, end_time: float, step: float = 0.05) -> Dict[str, Any]:
    """Return the isolated-vocal loudness profile in a window: pauses (silence gaps) and strong syllable onsets.

    Use it to see where phrases really start/end before moving lines.

    Args:
        title: Project title.
        start_time: Window start in seconds.
        end_time: Window end in seconds.
        step: Analysis frame in seconds (default 0.05).
    """
    try:
        import numpy as np
        import soundfile as sf

        s = _load_state(title)
        audio, sr = sf.read(s["vocals_wav"])
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        times = np.arange(max(0.0, start_time), end_time, step)
        rms = np.array([
            float(np.sqrt(np.mean(audio[int(t * sr):int((t + step) * sr)] ** 2))) if int((t + step) * sr) > int(t * sr) else 0.0
            for t in times
        ])
        if not len(rms):
            return {"status": "error", "error": "Пустое окно"}
        peak = float(rms.max()) or 1.0
        norm = rms / peak
        silent = norm < 0.12
        pauses = []
        k = 0
        while k < len(silent):
            if silent[k]:
                j = k
                while j < len(silent) and silent[j]:
                    j += 1
                if (j - k) * step >= 0.12:
                    pauses.append({"start": round(float(times[k]), 2), "end": round(float(times[min(j, len(times) - 1)]), 2)})
                k = j
            else:
                k += 1
        onsets = [
            round(float(times[i]), 2)
            for i in range(1, len(norm))
            if norm[i] - norm[i - 1] > 0.25 and norm[i] > 0.4
        ]
        chars = " .:|#"
        profile = "".join(chars[min(4, int(v * 5))] for v in norm)
        return {
            "status": "success",
            "step": step,
            "profile": profile,
            "pauses": pauses,
            "onsets": onsets,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@server.tool()
def set_line_timing(title: str, line_index: int, new_start: float, new_end: float, realign_by_vocals: bool = True) -> Dict[str, Any]:
    """Move/stretch one line to [new_start, new_end] (neighbours are trimmed if they overlap), then optionally
    re-align its words and syllables to the vocal inside that window (MMS_FA CTC).

    Args:
        title: Project title.
        line_index: 0-based line index.
        new_start: New line start (seconds).
        new_end: New line end (seconds).
        realign_by_vocals: Re-run vocal alignment of words inside the new window (default True).
    """
    import copy

    from karaoke.aligner import realign_lines_by_vocals

    try:
        s = _load_state(title)
        prev = copy.deepcopy(s)
        lines = s.get("lines") or []
        if not (0 <= line_index < len(lines)) or not lines[line_index]:
            return {"status": "error", "error": f"Неверный индекс строки {line_index}"}
        new_start = round(max(0.0, new_start), 2)
        new_end = round(max(new_start + 0.15, new_end), 2)
        line = lines[line_index]
        o_s, o_e = float(line[0]["start"]), float(line[-1]["end"])
        span = max(0.01, o_e - o_s)
        k = (new_end - new_start) / span
        for w in line:
            w["start"] = round(new_start + (float(w["start"]) - o_s) * k, 2)
            w["end"] = round(new_start + (float(w["end"]) - o_s) * k, 2)
            w.pop("syllable_timings", None)
        _trim_neighbours(lines, line_index)
        if realign_by_vocals and s.get("vocals_wav"):
            lines, _ = realign_lines_by_vocals(lines, Path(s["vocals_wav"]), [line_index])
        s["lines"] = lines
        _save_state(title, s, "manual", prev)
        notify_studio_ui("project_updated", title, f"Строка {line_index} перенесена через MCP", "timing_shifted")
        return {"status": "success", "line": _fmt_line(line_index, lines[line_index])}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _trim_neighbours(lines: List[List[Dict[str, Any]]], idx: int) -> None:
    """Trims previous/next lines so they never overlap line `idx` (keeps min 0.08s per word)."""
    cur = lines[idx]
    c_s, c_e = float(cur[0]["start"]), float(cur[-1]["end"])
    if idx > 0 and lines[idx - 1]:
        prev = lines[idx - 1]
        if float(prev[-1]["end"]) > c_s:
            _compress_line_into(prev, float(prev[0]["start"]), c_s)
    if idx + 1 < len(lines) and lines[idx + 1]:
        nxt = lines[idx + 1]
        if float(nxt[0]["start"]) < c_e:
            _compress_line_into(nxt, c_e, max(c_e + 0.08 * len(nxt), float(nxt[-1]["end"])))


def _compress_line_into(line: List[Dict[str, Any]], new_s: float, new_e: float) -> None:
    o_s, o_e = float(line[0]["start"]), float(line[-1]["end"])
    span = max(0.01, o_e - o_s)
    new_e = max(new_e, new_s + 0.08 * len(line))
    k = (new_e - new_s) / span
    for w in line:
        w["start"] = round(new_s + (float(w["start"]) - o_s) * k, 2)
        w["end"] = round(new_s + (float(w["end"]) - o_s) * k, 2)
        w.pop("syllable_timings", None)


@server.tool()
def set_word_timings(title: str, line_index: int, words: List[Dict[str, float]]) -> Dict[str, Any]:
    """Set exact start/end for every word of one line (precise manual fix).

    Args:
        title: Project title.
        line_index: 0-based line index.
        words: List of {"start": float, "end": float} — one entry per word of the line, in order.
    """
    import copy

    from karaoke.aligner import compute_vocal_rms_envelope, estimate_acoustic_syllable_timings

    try:
        s = _load_state(title)
        prev = copy.deepcopy(s)
        lines = s.get("lines") or []
        if not (0 <= line_index < len(lines)):
            return {"status": "error", "error": f"Неверный индекс строки {line_index}"}
        line = lines[line_index]
        if len(words) != len(line):
            return {"status": "error", "error": f"В строке {len(line)} слов, передано {len(words)}"}
        rms, hop = compute_vocal_rms_envelope(Path(s["vocals_wav"])) if s.get("vocals_wav") else (None, 0.01)
        for w, t in zip(line, words):
            w["start"] = round(float(t["start"]), 2)
            w["end"] = round(float(t["end"]), 2)
            w.pop("syllable_timings", None)
            explicit_syl = t.get("syllables") or t.get("syllable_timings")
            if explicit_syl:
                w["syllable_timings"] = [
                    {
                        "text": str(s.get("text", "")),
                        "start": round(float(s["start"]), 3),
                        "end": round(float(s["end"]), 3),
                    }
                    for s in explicit_syl
                ]
            elif rms is not None and len(rms):
                st = estimate_acoustic_syllable_timings(w["text"], w["start"], w["end"], rms, hop)
                if len(st) > 1:
                    w["syllable_timings"] = st
        _trim_neighbours(lines, line_index)
        s["lines"] = lines
        _save_state(title, s, "manual", prev)
        notify_studio_ui("project_updated", title, f"Слова строки {line_index} обновлены через MCP", "timing_shifted")
        return {"status": "success", "line": _fmt_line(line_index, lines[line_index])}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@server.tool()
def shift_lines(title: str, from_index: int, to_index: int, delta_seconds: float) -> Dict[str, Any]:
    """Shift a block of consecutive lines [from_index..to_index] by delta_seconds (keeps internal word timings).

    Args:
        title: Project title.
        from_index: First line index (inclusive).
        to_index: Last line index (inclusive).
        delta_seconds: Positive = later, negative = earlier.
    """
    import copy

    try:
        s = _load_state(title)
        prev = copy.deepcopy(s)
        lines = s.get("lines") or []
        if not (0 <= from_index <= to_index < len(lines)):
            return {"status": "error", "error": "Неверный диапазон строк"}
        for i in range(from_index, to_index + 1):
            for w in lines[i]:
                w["start"] = round(max(0.0, float(w["start"]) + delta_seconds), 2)
                w["end"] = round(max(0.0, float(w["end"]) + delta_seconds), 2)
                for t in w.get("syllable_timings", []) or []:
                    t["start"] = round(float(t["start"]) + delta_seconds, 3)
                    t["end"] = round(float(t["end"]) + delta_seconds, 3)
        _trim_neighbours(lines, from_index)
        _trim_neighbours(lines, to_index)
        s["lines"] = lines
        _save_state(title, s, "manual", prev)
        notify_studio_ui("project_updated", title, "Блок строк сдвинут через MCP", "timing_shifted")
        return {"status": "success", "lines": [_fmt_line(i, lines[i]) for i in range(from_index, to_index + 1)]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@server.tool()
def realign_lines(title: str, line_indices: List[int], mode: str = "vocals") -> Dict[str, Any]:
    """Re-generate timings of specific lines.

    Args:
        title: Project title.
        line_indices: 0-based line indices to re-align.
        mode: 'vocals' = MMS_FA CTC forced alignment of words/syllables inside each line's current window;
              'whisper' = restore raw Whisper word timings for those lines (if every word can be matched).
    """
    import copy

    from karaoke.aligner import compute_vocal_rms_envelope, realign_lines_by_vocals
    from karaoke.alignment_qa import _refresh_word_syllable_timings, whisper_line_candidate

    try:
        s = _load_state(title)
        prev = copy.deepcopy(s)
        lines = s.get("lines") or []
        vocals = Path(s["vocals_wav"]) if s.get("vocals_wav") else None
        updated: List[int] = []
        if mode == "whisper":
            rms, hop = compute_vocal_rms_envelope(vocals)
            for idx in line_indices:
                if not (0 <= idx < len(lines)):
                    continue
                cand = whisper_line_candidate(lines[idx], s.get("recognized_words"))
                if cand:
                    for w in cand:
                        _refresh_word_syllable_timings(w, rms, hop)
                    lines[idx] = cand
                    _trim_neighbours(lines, idx)
                    updated.append(idx)
        else:
            lines, updated = realign_lines_by_vocals(lines, vocals, line_indices)
        s["lines"] = lines
        _save_state(title, s, "realign_vocals" if mode != "whisper" else "manual", prev)
        notify_studio_ui("project_updated", title, f"Пересчитано строк: {len(updated)}", "timing_shifted")
        return {"status": "success", "updated": updated, "lines": [_fmt_line(i, lines[i]) for i in updated]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@server.tool()
def list_timing_history(title: str) -> Dict[str, Any]:
    """List saved timing snapshots (versions) of a project, newest first."""
    from karaoke import timing_history

    return {"status": "success", "snapshots": timing_history.list_snapshots(WORK_DIR, title)}


@server.tool()
def restore_timing_snapshot(title: str, snapshot_id: str) -> Dict[str, Any]:
    """Restore project timings from a snapshot id (current version is saved to history first)."""
    import copy

    from karaoke import timing_history

    try:
        s = _load_state(title)
        snap = timing_history.load_snapshot(WORK_DIR, title, snapshot_id)
        if not snap:
            return {"status": "error", "error": "Версия не найдена"}
        prev = copy.deepcopy(s)
        s["lines"] = snap["lines"]
        _save_state(title, s, "restore", prev)
        notify_studio_ui("project_updated", title, "Версия таймингов восстановлена через MCP", "timing_shifted")
        return {"status": "success", "lines_count": len(s["lines"])}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@server.tool()
def get_models_catalog() -> Dict[str, Any]:
    """Get status of installed and available Whisper and Demucs AI models with disk sizes."""
    return {"models": get_models_status_list()}


def main():
    """Run the MCP server over stdio."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
