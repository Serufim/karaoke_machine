import json
import math
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from karaoke.aligner import (
    compute_vocal_rms_envelope,
    find_vocal_onset,
    find_vocal_offset,
    count_syllables,
    align_words_to_reference_lines,
    regroup_words_into_logical_lines,
    lines_to_editor_text,
    validate_karaoke_lines,
)
from karaoke.ass_writer import generate_ass_from_lines
from karaoke.transcriber import transcribe_vocals
from karaoke.video import find_ffmpeg


def align_audio_slice(
    title: str,
    start: float,
    end: float,
    text: str,
    mode: str = "whisper",
    work_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """
    Surgically calibrates lyrics timestamps for a specific audio slice [start, end].
    - 'whisper': Cuts vocals slice, transcribes with Whisper guided by text prompt, then aligns.
    - 'syllables_rms': Distributes words across actual vocal RMS energy envelope proportionally to syllables.
    """
    if work_dir is None:
        from karaoke.api.routes import WORK_DIR
        work_dir = WORK_DIR

    start = max(0.0, float(start))
    end = max(start + 0.2, float(end))
    text_clean = text.strip()
    if not text_clean:
        return []

    tokens = [t for t in text_clean.split() if t.strip()]
    if not tokens:
        return []

    state_file = work_dir / f"{title}_state.json"
    vocals_wav = None
    if state_file.exists():
        try:
            state_data = json.loads(state_file.read_text(encoding="utf-8"))
            if state_data.get("vocals_wav") and Path(state_data["vocals_wav"]).exists():
                vocals_wav = Path(state_data["vocals_wav"])
        except Exception:
            pass

    # Method 1: Whisper neural alignment on the slice
    if mode == "whisper" and vocals_wav:
        slice_wav = work_dir / f"{title}_slice_{int(start * 100)}_{int(end * 100)}.wav"
        ffmpeg_bin = find_ffmpeg()
        try:
            subprocess.run(
                [
                    ffmpeg_bin, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                    "-i", str(vocals_wav),
                    "-c:a", "pcm_s16le",
                    str(slice_wav),
                ],
                check=True,
            )

            res = transcribe_vocals(
                vocals_path=slice_wav,
                model_size="large-v3-turbo",
                language="ru",
                initial_prompt=text_clean,
                condition_on_previous_text=False,
                vad=None,
            )

            rec_words = []
            for seg in res.get("segments", []):
                for w in seg.get("words", []):
                    w_start = round(float(w.get("start", 0.0)) + start, 2)
                    w_end = round(float(w.get("end", w_start + 0.25)) + start, 2)
                    txt = str(w.get("text", w.get("word", ""))).strip()
                    if txt:
                        rec_words.append({
                            "text": txt,
                            "start": w_start,
                            "end": w_end,
                            "syllables": count_syllables(txt),
                        })

            if rec_words:
                aligned = align_words_to_reference_lines(
                    rec_words,
                    [text_clean],
                    vocals_path=vocals_wav,
                    strict_repeats=False,
                )
                if aligned:
                    flattened = [w for line in aligned for w in line]
                    if flattened:
                        return flattened
        except Exception as e:
            print(f"[ManualAlign] Whisper slice alignment warning: {e}. Falling back to syllables & RMS.")
        finally:
            if slice_wav.exists():
                try:
                    slice_wav.unlink()
                except Exception:
                    pass

    # Method 2: Syllable count + Vocal RMS energy envelope (robust fallback)
    rms, hop_s = compute_vocal_rms_envelope(vocals_wav) if vocals_wav else (None, 0.01)
    if rms is not None and len(rms) > 0:
        real_onset = find_vocal_onset(rms, hop_s, start, end)
        real_offset = find_vocal_offset(rms, hop_s, real_onset, end)
        if real_offset > real_onset + 0.2:
            start = real_onset
            end = real_offset

    sylls = [count_syllables(t) for t in tokens]
    tot_s = max(1, sum(sylls))
    dur = max(0.15 * len(tokens), end - start)
    cursor = start
    result = []
    for t, s in zip(tokens, sylls):
        step = dur * (s / tot_s)
        w_start = round(cursor, 2)
        w_end = round(cursor + step, 2)
        if w_end <= w_start:
            w_end = round(w_start + 0.12, 2)
        result.append({
            "text": t,
            "start": w_start,
            "end": w_end,
            "syllables": s,
        })
        cursor += step

    return result


def render_slice_preview_video(
    title: str,
    start: float,
    end: float,
    words: List[Dict[str, Any]],
    work_dir: Optional[Path] = None,
) -> Tuple[Path, float]:
    """
    Renders an ultrafast preview MP4 video for the slice [start, end] with project background
    and animated ASS karaoke sweep highlighting.
    """
    if work_dir is None:
        from karaoke.api.routes import WORK_DIR
        work_dir = WORK_DIR

    start = max(0.0, float(start))
    end = max(start + 0.3, float(end))
    slice_dur = round(end - start, 2)

    state_file = work_dir / f"{title}_state.json"
    state_data: Dict[str, Any] = {}
    if state_file.exists():
        try:
            state_data = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 1. Backing audio slice
    no_vocals_wav = Path(state_data.get("no_vocals_wav", ""))
    slice_audio = work_dir / f"{title}_slice_audio.wav"
    ffmpeg_bin = find_ffmpeg()

    if no_vocals_wav.exists():
        subprocess.run(
            [
                ffmpeg_bin, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                "-i", str(no_vocals_wav),
                "-c:a", "pcm_s16le",
                str(slice_audio),
            ],
            check=True,
        )
    else:
        # Generate silence audio if no wav available
        subprocess.run(
            [
                ffmpeg_bin, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
                "-t", f"{slice_dur:.3f}",
                "-c:a", "pcm_s16le",
                str(slice_audio),
            ],
            check=True,
        )

    # 2. Shift word timestamps relative to slice start (clip starts at 0.0s)
    shifted_words = []
    for w in words:
        w_start = max(0.0, round(float(w["start"]) - start, 2))
        w_end = max(w_start + 0.08, round(float(w["end"]) - start, 2))
        shifted_words.append({
            "text": str(w["text"]),
            "start": w_start,
            "end": w_end,
            "syllables": int(w.get("syllables", count_syllables(str(w["text"])))),
        })

    preview_ass = work_dir / f"{title}_slice_preview.ass"
    cover_edge_colors = state_data.get("cover_edge_colors")
    generate_ass_from_lines(
        lines=[shifted_words],
        output_path=preview_ass,
        title=title,
        num_lines=3,
        visual_effects="sparkles_pulse",
        edge_color_mode="cyberpunk",
        cover_edge_colors=cover_edge_colors,
        font_size_mode="large",
        highlight_color="gold_neon",
    )

    # 3. Resolve background
    bg: Optional[Path] = None
    if state_data.get("custom_bg") and Path(state_data["custom_bg"]).exists():
        bg = Path(state_data["custom_bg"])
    elif state_data.get("video_bg") and Path(state_data["video_bg"]).exists():
        bg = Path(state_data["video_bg"])
    elif state_data.get("cover_image") and Path(state_data["cover_image"]).exists():
        bg = Path(state_data["cover_image"])

    preview_video = work_dir / f"{title}_slice_preview.mp4"
    ass_escaped = str(preview_ass.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

    is_video_bg = False
    if bg and bg.exists():
        suf = bg.suffix.lower()
        if suf in (".mp4", ".mov", ".mkv", ".webm", ".avi"):
            is_video_bg = True

    vf_base = f"scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,subtitles='{ass_escaped}'"

    if is_video_bg and bg:
        cmd = [
            ffmpeg_bin, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-i", str(bg),
            "-i", str(slice_audio),
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", vf_base,
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-t", f"{slice_dur:.3f}",
            str(preview_video),
        ]
    elif bg and bg.exists():
        cmd = [
            ffmpeg_bin, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-loop", "1", "-t", f"{slice_dur:.3f}",
            "-i", str(bg),
            "-i", str(slice_audio),
            "-vf", vf_base,
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(preview_video),
        ]
    else:
        cmd = [
            ffmpeg_bin, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=0x0a0c14:s=1920x1080:r=30:d={slice_dur:.3f}",
            "-i", str(slice_audio),
            "-vf", f"subtitles='{ass_escaped}'",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(preview_video),
        ]

    subprocess.run(cmd, check=True)
    return preview_video, slice_dur


def apply_slice_to_project(
    title: str,
    start: float,
    end: float,
    words: List[Dict[str, Any]],
    work_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Splices surgically calibrated words into the project's lines, updates editor text,
    and persists the updated state to disk.
    """
    if work_dir is None:
        from karaoke.api.routes import WORK_DIR
        work_dir = WORK_DIR

    state_file = work_dir / f"{title}_state.json"
    if not state_file.exists():
        raise FileNotFoundError(f"Проект '{title}' не найден.")

    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    existing_lines = state_data.get("lines", [])

    # Extract all existing words
    all_words: List[Dict[str, Any]] = []
    for line in existing_lines:
        if isinstance(line, list):
            for w in line:
                all_words.append(dict(w))
        elif isinstance(line, dict):
            all_words.append(dict(line))

    # Filter out words that overlap the slice [start, end]
    preserved_words = []
    for w in all_words:
        w_s = float(w.get("start", 0.0))
        w_e = float(w.get("end", w_s + 0.1))
        # Keep word if it ends before start or starts after end
        if w_e <= start + 0.04 or w_s >= end - 0.04:
            preserved_words.append(w)

    # Add newly calibrated words
    clean_new_words = []
    for w in words:
        txt = str(w.get("text", "")).strip()
        if not txt:
            continue
        w_s = round(float(w.get("start", start)), 2)
        w_e = round(float(w.get("end", w_s + 0.2)), 2)
        if w_e <= w_s:
            w_e = round(w_s + 0.12, 2)
        clean_new_words.append({
            "text": txt,
            "start": w_s,
            "end": w_e,
            "syllables": int(w.get("syllables", count_syllables(txt))),
        })

    merged_words = preserved_words + clean_new_words
    merged_words.sort(key=lambda x: (float(x["start"]), float(x["end"])))

    # Ensure monotonic non-overlapping timestamps
    prev_end = 0.0
    for w in merged_words:
        s = float(w["start"])
        e = float(w["end"])
        if s < prev_end:
            s = prev_end
        if e <= s:
            e = round(s + 0.08, 2)
        w["start"] = round(s, 2)
        w["end"] = round(e, 2)
        prev_end = e

    new_lines = regroup_words_into_logical_lines(merged_words)
    validate_karaoke_lines(new_lines)
    new_editor_text = lines_to_editor_text(new_lines)

    state_data["lines"] = new_lines
    state_data["editor_text"] = new_editor_text
    state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "applied",
        "lines": new_lines,
        "editor_text": new_editor_text,
        "words_count": len(clean_new_words),
    }
