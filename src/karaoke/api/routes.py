import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from PIL import Image
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from karaoke.aligner import (
    editor_text_to_lines,
    lines_to_editor_text,
    regroup_editor_lines,
    split_long_editor_lines,
)
from karaoke.api.websocket import ws_manager
from karaoke.cancel_manager import (
    GenerationCancelledError,
    request_cancel,
    reset_cancel,
)
from karaoke.cli import analyze_and_transcribe, render_from_state
from karaoke.downloader import ensure_project_cover
from karaoke.mixer import compute_waveform_peaks, detect_chorus_fx_intervals
from karaoke.separator import DEMUCS_MODELS
from karaoke.transcriber import WHISPER_MODELS
from karaoke.video import extract_cover_edge_colors
from karaoke.hardware import get_hardware_profile_dict
from karaoke.charts import get_platform_chart
from karaoke.model_manager import (
    get_models_status_list,
    start_model_download_background,
    delete_model_cache,
    MODEL_CATALOG,
)
from karaoke.slice_editor import (
    align_audio_slice,
    render_slice_preview_video,
    apply_slice_to_project,
)

router = APIRouter(prefix="/api")

OUTPUT_DIR = Path("./output").resolve()
WORK_DIR = OUTPUT_DIR / "work"


class DownloadModelRequest(BaseModel):
    model_id: str



class RegroupRequest(BaseModel):
    editor_text: str
    original_lines: Optional[List[Any]] = None


class SplitLinesRequest(BaseModel):
    editor_text: str
    original_lines: Optional[List[Any]] = None
    max_chars: int = 38
    max_words: int = 8


class AutoFxRequest(BaseModel):
    title: str


class RebuildRequest(BaseModel):
    title: str
    editor_text: Optional[str] = None
    vocal_volume: float = 0.0
    vocal_intervals: Optional[List[Dict[str, Any]]] = None
    fx_intervals: Optional[List[Dict[str, Any]]] = None
    emoji_intervals: Optional[List[Dict[str, Any]]] = None
    num_lines: int = 4
    video_quality: str = "balanced"
    use_cover_bg: bool = False
    use_video_bg: bool = False
    visual_effects: str = "sparkles_pulse"
    edge_color_mode: str = "cyberpunk"
    font_size_mode: str = "large"
    highlight_color: str = "gold_neon"
    dual_audio_mp4: bool = True
    watermark_text: Optional[str] = None
    export_dir: Optional[str] = None


class DjExportRequest(BaseModel):
    editor_text: Optional[str] = None
    vocal_volume: float = 0.0
    vocal_intervals: Optional[List[Dict[str, Any]]] = None
    export_dir: Optional[str] = None


class OpenFolderRequest(BaseModel):
    path: str


class SelectFolderRequest(BaseModel):
    initial_dir: Optional[str] = None


class SliceAlignRequest(BaseModel):
    title: str
    start: float
    end: float
    text: str
    mode: str = "whisper"


class SlicePreviewRequest(BaseModel):
    title: str
    start: float
    end: float
    words: List[Dict[str, Any]]


class SliceApplyRequest(BaseModel):
    title: str
    start: float
    end: float
    words: List[Dict[str, Any]]


class UpdateStateRequest(BaseModel):
    vocal_intervals: Optional[List[Dict[str, Any]]] = None
    fx_intervals: Optional[List[Dict[str, Any]]] = None
    emoji_intervals: Optional[List[Dict[str, Any]]] = None
    lines: Optional[List[Any]] = None
    editor_text: Optional[str] = None


@router.get("/health")
def health_check() -> Dict[str, str]:
    return {"status": "ok"}


@router.get("/models")
def get_available_models() -> Dict[str, List[str]]:
    return {
        "demucs": DEMUCS_MODELS,
        "whisper": WHISPER_MODELS,
    }


@router.get("/system/hardware")
def get_hardware_info() -> Dict[str, Any]:
    """Returns detected hardware profile, GPU/CUDA/MPS capabilities, and recommended models."""
    return get_hardware_profile_dict()


@router.get("/charts")
def get_charts(platform: str = "yandex", country: str = "ru", limit: int = 50) -> Dict[str, Any]:
    """Fetches music charts for the specified platform and country."""
    return get_platform_chart(platform=platform, country=country, limit=limit)


def get_preset_folders() -> Dict[str, str]:
    home = Path.home()
    presets = {
        "output": str(OUTPUT_DIR.resolve()),
        "desktop": str(home / "Desktop"),
        "downloads": str(home / "Downloads"),
        "music": str(home / "Music"),
    }
    return {k: v for k, v in presets.items() if Path(v).exists() or k == "output"}


def pick_folder_native(initial_dir: Optional[str] = None) -> Optional[str]:
    # 1. Check pywebview active windows
    try:
        import webview
        if webview.windows and len(webview.windows) > 0:
            res = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG, directory=initial_dir or "")
            if res and len(res) > 0:
                return str(res[0])
            return None
    except Exception:
        pass

    # 2. macOS Cocoa choose folder
    if sys.platform == "darwin":
        try:
            default_loc = f'default location POSIX file "{initial_dir}"' if initial_dir and Path(initial_dir).exists() else ""
            cmd = ['osascript', '-e', f'POSIX path of (choose folder with prompt "Выберите папку для сохранения караоке" {default_loc})']
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            chosen = res.stdout.strip()
            if chosen:
                return chosen
        except Exception:
            return None

    # 3. Windows PowerShell FolderBrowserDialog
    elif sys.platform == "win32":
        try:
            ps_cmd = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
                "$f.Description = 'Выберите папку для сохранения караоке'; "
                "if ($f.ShowDialog() -eq 'OK') { Write-Output $f.SelectedPath }"
            )
            res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
            chosen = res.stdout.strip()
            if chosen:
                return chosen
        except Exception:
            return None

    # 4. Tkinter fallback
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        folder = filedialog.askdirectory(initialdir=initial_dir or str(Path.home()))
        root.destroy()
        if folder:
            return folder
    except Exception:
        pass

    return None


def open_folder_in_os(folder_path: Path):
    if not folder_path.exists():
        folder_path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        subprocess.run(["open", str(folder_path)])
    elif sys.platform == "win32":
        os.startfile(str(folder_path))
    else:
        subprocess.run(["xdg-open", str(folder_path)])


@router.get("/system/folders")
def get_system_preset_folders() -> Dict[str, Any]:
    """Returns detected common folders for quick export selection."""
    return {"presets": get_preset_folders(), "default": str(OUTPUT_DIR.resolve())}


@router.post("/system/select-folder")
def select_folder_dialog(req: SelectFolderRequest) -> Dict[str, Any]:
    """Opens OS native folder picker dialog and returns selected path."""
    chosen = pick_folder_native(req.initial_dir)
    return {"selected_path": chosen}


@router.post("/system/open-folder")
def open_folder_endpoint(req: OpenFolderRequest) -> Dict[str, Any]:
    """Opens target folder in Finder / Windows Explorer."""
    p = Path(req.path)
    if not p.is_dir() and p.parent.is_dir():
        p = p.parent
    open_folder_in_os(p)
    return {"status": "opened", "path": str(p)}


@router.get("/models/catalog")
def get_models_catalog() -> Dict[str, Any]:
    """Returns all supported models with status (downloaded / in progress), disk size, and resource requirements."""
    return {"models": get_models_status_list()}


@router.post("/models/download")
def download_model_endpoint(req: DownloadModelRequest) -> Dict[str, Any]:
    """Triggers asynchronous download of model weights with progress reporting via WebSockets."""
    if req.model_id not in MODEL_CATALOG:
        raise HTTPException(status_code=404, detail=f"Model '{req.model_id}' is not in catalog")

    def _progress_callback(info: Dict[str, Any]):
        ws_manager.broadcast_sync({
            "type": "model_progress",
            "model_id": info["model_id"],
            "status": info["status"],
            "progress": info["progress"],
            "message": info["message"],
        })

    start_model_download_background(req.model_id, progress_callback=_progress_callback)
    return {
        "status": "started",
        "model_id": req.model_id,
        "message": f"Загрузка модели {req.model_id} запущена",
    }


@router.delete("/models/{model_id:path}")
def delete_model_endpoint(model_id: str) -> Dict[str, Any]:
    """Deletes cached model files to free disk space."""
    if model_id not in MODEL_CATALOG:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' is not in catalog")

    success = delete_model_cache(model_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to delete model '{model_id}' (not found or in use)")

    return {
        "status": "deleted",
        "model_id": model_id,
        "message": f"Кэш модели {model_id} успешно очищен",
    }



@router.get("/projects")
def list_projects() -> Dict[str, List[Dict[str, Any]]]:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        WORK_DIR.glob("*_state.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    projects = []
    for f in files:
        title = f.stem.replace("_state", "")
        mtime = f.stat().st_mtime
        video_file = OUTPUT_DIR / f"{title}_karaoke.mp4"
        cover_file = WORK_DIR / f"{title}_cover.png"
        projects.append({
            "title": title,
            "mtime": mtime,
            "has_video": video_file.exists(),
            "has_cover": cover_file.exists(),
        })
    return {"projects": projects}


@router.get("/projects/{title}")
def get_project_state(title: str) -> Dict[str, Any]:
    state_file = WORK_DIR / f"{title}_state.json"
    if not state_file.exists():
        raise HTTPException(status_code=404, detail=f"Проект '{title}' не найден.")

    try:
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка чтения state.json: {e}")

    changed = False
    no_vocals_wav = state_data.get("no_vocals_wav")
    vocals_wav = state_data.get("vocals_wav")

    # Ensure waveform peaks exist
    if (not state_data.get("inst_peaks") or not state_data.get("duration")) and no_vocals_wav and Path(no_vocals_wav).exists():
        i_peaks, dur = compute_waveform_peaks(Path(no_vocals_wav))
        v_peaks, _ = compute_waveform_peaks(Path(vocals_wav)) if vocals_wav and Path(vocals_wav).exists() else ([], 0.0)
        state_data["inst_peaks"] = i_peaks
        state_data["vocal_peaks"] = v_peaks
        state_data["duration"] = dur
        if not state_data.get("fx_intervals") and vocals_wav and Path(vocals_wav).exists():
            state_data["fx_intervals"] = detect_chorus_fx_intervals(Path(no_vocals_wav), Path(vocals_wav))
        changed = True

    # Ensure cover exists
    cover_img = state_data.get("cover_image")
    if not cover_img or not Path(cover_img).exists():
        cover_img = ensure_project_cover(title, state_file.parent)
        if cover_img:
            state_data["cover_image"] = str(cover_img)
            changed = True

    if cover_img and Path(cover_img).exists() and not state_data.get("cover_edge_colors"):
        state_data["cover_edge_colors"] = extract_cover_edge_colors(Path(cover_img))
        changed = True

    # Ensure reference_lyrics is populated (reconstructing from editor_text for legacy projects)
    if not state_data.get("reference_lyrics"):
        editor_text = state_data.get("editor_text") or ""
        clean_lines = []
        for line in editor_text.splitlines():
            line_str = re.sub(r"^\[\d+:\d+\.\d+\s*->\s*\d+:\d+\.\d+\]\s*", "", line.strip())
            if line_str:
                clean_lines.append(line_str)
        if clean_lines:
            state_data["reference_lyrics"] = "\n".join(clean_lines)

    # Ensure generation_params exists
    if not state_data.get("generation_params"):
        state_data["generation_params"] = {
            "model_size": "large-v3-turbo",
            "demucs_model": "htdemucs",
            "vad": "auditok",
            "use_ctc_align": False,
            "use_video_bg": bool(state_data.get("video_bg")),
            "condition_on_previous_text": False,
            "strict_repeats": False,
        }

    # Ensure source_type exists
    if not state_data.get("source_type"):
        src = state_data.get("source") or ""
        state_data["source_type"] = "url" if str(src).startswith(("http://", "https://", "ytsearch")) else "file"

    if changed:
        state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

    video_file = OUTPUT_DIR / f"{title}_karaoke.mp4"
    state_data["has_video"] = video_file.exists()

    return state_data


@router.put("/projects/{title}")
def update_project_state(title: str, payload: UpdateStateRequest) -> Dict[str, Any]:
    state_file = WORK_DIR / f"{title}_state.json"
    if not state_file.exists():
        raise HTTPException(status_code=404, detail=f"Проект '{title}' не найден.")

    state_data = json.loads(state_file.read_text(encoding="utf-8"))

    if payload.vocal_intervals is not None:
        state_data["vocal_intervals"] = payload.vocal_intervals
    if payload.fx_intervals is not None:
        state_data["fx_intervals"] = payload.fx_intervals
    if payload.emoji_intervals is not None:
        state_data["emoji_intervals"] = payload.emoji_intervals
    if payload.editor_text is not None:
        state_data["editor_text"] = payload.editor_text
        state_data["lines"] = editor_text_to_lines(payload.editor_text, original_lines=state_data.get("lines", []))
    elif payload.lines is not None:
        state_data["lines"] = payload.lines
        state_data["editor_text"] = lines_to_editor_text(payload.lines)

    state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "saved", "title": title}


@router.post("/projects/{title}/cover")
async def upload_cover_image(title: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    state_file = WORK_DIR / f"{title}_state.json"
    if not state_file.exists():
        raise HTTPException(status_code=404, detail=f"Проект '{title}' не найден.")

    state_data = json.loads(state_file.read_text(encoding="utf-8"))

    try:
        img = Image.open(file.file).convert("RGB")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Недопустимый формат изображения: {e}")

    cover_path = WORK_DIR / f"{title}_cover.png"
    img.save(cover_path, format="PNG")

    cover_edge_colors = extract_cover_edge_colors(cover_path)
    state_data["cover_image"] = str(cover_path)
    state_data["cover_edge_colors"] = cover_edge_colors

    state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "ok",
        "cover_url": f"/api/media/{title}/cover?t={int(time.time() * 1000)}",
        "cover_image": str(cover_path),
        "cover_edge_colors": cover_edge_colors,
    }


@router.post("/projects/{title}/background")
async def upload_background_image(title: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    state_file = WORK_DIR / f"{title}_state.json"
    if not state_file.exists():
        raise HTTPException(status_code=404, detail=f"Проект '{title}' не найден.")

    state_data = json.loads(state_file.read_text(encoding="utf-8"))

    suffix = Path(file.filename or "bg.png").suffix or ".png"
    bg_path = WORK_DIR / f"{title}_custom_bg{suffix}"
    with bg_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    state_data["custom_bg"] = str(bg_path)
    state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "status": "ok",
        "bg_path": str(bg_path),
    }


@router.post("/tools/regroup-lines")
def regroup_lines(payload: RegroupRequest) -> Dict[str, Any]:
    lines = editor_text_to_lines(payload.editor_text, original_lines=payload.original_lines or [])
    new_lines = regroup_editor_lines(lines)
    new_editor_text = lines_to_editor_text(new_lines)
    return {
        "lines": new_lines,
        "editor_text": new_editor_text,
        "original_count": len(lines),
        "new_count": len(new_lines),
    }


@router.post("/tools/split-lines")
def split_lines(payload: SplitLinesRequest) -> Dict[str, Any]:
    lines = editor_text_to_lines(payload.editor_text, original_lines=payload.original_lines or [])
    new_lines = split_long_editor_lines(
        lines,
        max_chars=payload.max_chars,
        max_words=payload.max_words,
    )
    new_editor_text = lines_to_editor_text(new_lines)
    return {
        "lines": new_lines,
        "editor_text": new_editor_text,
        "original_count": len(lines),
        "new_count": len(new_lines),
        "split_count": len(new_lines) - len(lines),
    }


@router.post("/tools/auto-fx")
def auto_detect_fx(payload: AutoFxRequest) -> Dict[str, Any]:
    state_file = WORK_DIR / f"{payload.title}_state.json"
    if not state_file.exists():
        raise HTTPException(status_code=404, detail="Проект не найден.")

    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    no_vocals = Path(state_data.get("no_vocals_wav", ""))
    vocals = Path(state_data.get("vocals_wav", ""))
    if not no_vocals.exists() or not vocals.exists():
        raise HTTPException(status_code=400, detail="Аудиофайлы проекта не найдены на диске.")

    auto_fx = detect_chorus_fx_intervals(no_vocals, vocals)
    state_data["fx_intervals"] = auto_fx
    state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"fx_intervals": auto_fx, "count": len(auto_fx)}


@router.post("/tools/slice-align")
def slice_align_endpoint(payload: SliceAlignRequest) -> Dict[str, Any]:
    try:
        words = align_audio_slice(
            title=payload.title,
            start=payload.start,
            end=payload.end,
            text=payload.text,
            mode=payload.mode,
            work_dir=WORK_DIR,
        )
        return {
            "status": "ok",
            "words": words,
            "count": len(words),
            "start": payload.start,
            "end": payload.end,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка калибровки участка: {e}")


@router.post("/tools/slice-preview")
def slice_preview_endpoint(payload: SlicePreviewRequest) -> Dict[str, Any]:
    try:
        preview_file, dur = render_slice_preview_video(
            title=payload.title,
            start=payload.start,
            end=payload.end,
            words=payload.words,
            work_dir=WORK_DIR,
        )
        return {
            "status": "ok",
            "duration": dur,
            "preview_url": f"/api/media/{payload.title}/slice-preview?t={int(time.time() * 1000)}",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка генерации превью участка: {e}")


@router.post("/tools/slice-apply")
def slice_apply_endpoint(payload: SliceApplyRequest) -> Dict[str, Any]:
    try:
        res = apply_slice_to_project(
            title=payload.title,
            start=payload.start,
            end=payload.end,
            words=payload.words,
            work_dir=WORK_DIR,
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка сохранения участка: {e}")


@router.post("/pipeline/cancel")
def cancel_job() -> Dict[str, Any]:
    killed = request_cancel()
    ws_manager.broadcast_threadsafe({
        "type": "progress",
        "fraction": 0.0,
        "stage": "cancelled",
        "message": f"🛑 Генерация остановлена пользователем (остановлено процессов: {killed}).",
    })
    return {"status": "cancelled", "killed_count": killed}


def _run_generate_task(
    source: str,
    model_size: str,
    demucs_model: str,
    language: str,
    reference_lyrics: str,
    use_ctc_align: bool,
    download_video: bool,
    cookies_browser: Optional[str],
    vocal_volume: float,
    num_lines: int,
    video_quality: str,
    temp_upload_file: Optional[Path] = None,
    custom_bg: Optional[Union[str, Path]] = None,
    temp_bg_file: Optional[Path] = None,
    condition_on_previous_text: bool = False,
    vad: Optional[str] = "auditok",
    strict_repeats: bool = False,
):
    reset_cancel()

    def update_progress(msg: str, frac: float):
        ws_manager.broadcast_threadsafe({
            "type": "progress",
            "fraction": frac,
            "message": msg,
            "stage": "analyzing",
        })

    try:
        update_progress("Запуск анализа и разделения вокала...", 0.05)
        state_data = analyze_and_transcribe(
            source=source,
            output_dir=OUTPUT_DIR,
            model_size=model_size,
            demucs_model=demucs_model,
            language=language,
            reference_lyrics=reference_lyrics,
            use_ctc_align=use_ctc_align,
            download_video=download_video,
            cookies_browser=cookies_browser,
            custom_bg=custom_bg,
            condition_on_previous_text=condition_on_previous_text,
            vad=vad,
            strict_repeats=strict_repeats,
            progress_callback=update_progress,
        )

        bg_param = Path(state_data["custom_bg"]) if state_data.get("custom_bg") else None
        use_cov = False if bg_param else (not download_video)
        use_vid = download_video if not bg_param else False

        update_progress("Сборка базового видео караоке...", 0.70)
        final_video, _mixed_audio, updated_editor_text = render_from_state(
            state_data=state_data,
            output_dir=OUTPUT_DIR,
            editor_text=state_data.get("editor_text"),
            vocal_volume=vocal_volume,
            num_lines=num_lines,
            video_quality=video_quality,
            background=bg_param,
            use_cover_bg=use_cov,
            use_video_bg=use_vid,
            progress_callback=update_progress,
        )

        ws_manager.broadcast_threadsafe({
            "type": "completed",
            "action": "generate",
            "title": state_data["title"],
            "video_path": str(final_video),
            "message": f"🎉 Проект '{state_data['title']}' успешно сгенерирован!",
        })
    except GenerationCancelledError:
        ws_manager.broadcast_threadsafe({
            "type": "cancelled",
            "message": "🛑 Генерация остановлена пользователем.",
        })
    except Exception as e:
        ws_manager.broadcast_threadsafe({
            "type": "error",
            "message": f"Ошибка генерации: {e}",
        })
    finally:
        if temp_upload_file and temp_upload_file.exists():
            try:
                temp_upload_file.unlink()
            except Exception:
                pass
        if temp_bg_file and temp_bg_file.exists():
            try:
                temp_bg_file.unlink()
            except Exception:
                pass


@router.post("/pipeline/generate")
async def start_generate(
    file: Optional[UploadFile] = File(None),
    bg_file: Optional[UploadFile] = File(None),
    cover_file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    existing_project_title: Optional[str] = Form(None),
    model_size: str = Form("large-v3-turbo"),
    demucs_model: str = Form("htdemucs"),
    language: str = Form("ru"),
    reference_lyrics: str = Form(""),
    use_ctc_align: bool = Form(False),
    use_video_bg: bool = Form(False),
    vocal_volume_pct: float = Form(0.0),
    num_lines: int = Form(4),
    video_quality: str = Form("balanced"),
    cookies_browser: str = Form("none"),
    condition_on_previous_text: bool = Form(False),
    vad: Optional[str] = Form("auditok"),
    strict_repeats: bool = Form(False),
):
    temp_upload_path = None
    existing_state_data = None
    if existing_project_title and existing_project_title.strip():
        proj_title = existing_project_title.strip()
        state_file = WORK_DIR / f"{proj_title}_state.json"
        if state_file.exists():
            try:
                existing_state_data = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    if file and file.filename:
        suffix = Path(file.filename).suffix
        temp_fd, temp_path_str = tempfile.mkstemp(suffix=suffix, prefix="karaoke_upload_")
        os.close(temp_fd)
        temp_upload_path = Path(temp_path_str)
        with temp_upload_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        source = str(temp_upload_path)
    elif url and url.strip():
        source = url.strip()
        if not (source.startswith("http://") or source.startswith("https://") or source.startswith("ytsearch")):
            source = f"ytsearch1:{source} audio"
    elif existing_state_data:
        proj_title = existing_state_data["title"]
        source = None
        candidates = [
            existing_state_data.get("source_audio"),
            WORK_DIR / f"{proj_title}_source.wav",
            WORK_DIR / f"{proj_title}_source.mp3",
            WORK_DIR / f"{proj_title}_source.m4a",
            WORK_DIR / f"{proj_title}_source.flac",
            WORK_DIR / f"{proj_title}.wav",
            existing_state_data.get("video_bg"),
        ]
        for cand in candidates:
            if cand and Path(cand).exists():
                source = str(Path(cand).resolve())
                break

        if not source:
            voc = existing_state_data.get("vocals_wav")
            inst = existing_state_data.get("no_vocals_wav")
            if voc and inst and Path(voc).exists() and Path(inst).exists():
                reconstructed_wav = WORK_DIR / f"{proj_title}_source.wav"
                ffmpeg_bin = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg" or "ffmpeg"
                try:
                    subprocess.run([
                        ffmpeg_bin, "-y",
                        "-i", str(voc),
                        "-i", str(inst),
                        "-filter_complex", "amix=inputs=2:duration=first:dropout_transition=0",
                        "-c:a", "pcm_s16le",
                        str(reconstructed_wav)
                    ], check=True, capture_output=True)
                    if reconstructed_wav.exists():
                        source = str(reconstructed_wav)
                except Exception:
                    pass

        if not source:
            raise HTTPException(status_code=400, detail="Не удалось найти аудиофайл проекта для перегенерации.")
    else:
        raise HTTPException(status_code=400, detail="Загрузите файл или укажите ссылку на YouTube.")

    temp_bg_path = None
    custom_bg_target = None
    target_img_file = bg_file or cover_file
    if target_img_file and target_img_file.filename:
        c_suffix = Path(target_img_file.filename).suffix or ".png"
        c_fd, c_path_str = tempfile.mkstemp(suffix=c_suffix, prefix="karaoke_custom_bg_")
        os.close(c_fd)
        temp_bg_path = Path(c_path_str)
        with temp_bg_path.open("wb") as buffer:
            shutil.copyfileobj(target_img_file.file, buffer)
        custom_bg_target = temp_bg_path
    elif existing_state_data:
        saved_bg = existing_state_data.get("custom_bg") or existing_state_data.get("cover_image")
        if saved_bg and Path(saved_bg).exists():
            custom_bg_target = Path(saved_bg)

    cb = cookies_browser if cookies_browser not in ("none", "file") else None
    vocal_vol = float(vocal_volume_pct) / 100.0

    t = threading.Thread(
        target=_run_generate_task,
        args=(
            source,
            model_size,
            demucs_model,
            language,
            reference_lyrics,
            use_ctc_align,
            use_video_bg,
            cb,
            vocal_vol,
            num_lines,
            video_quality,
            temp_upload_path,
            custom_bg_target,
            temp_bg_path,
            condition_on_previous_text,
            vad,
            strict_repeats,
        ),
        daemon=True,
    )
    t.start()
    return {"status": "started", "source": source}


def _run_rebuild_task(
    title: str,
    state_data: Dict[str, Any],
    editor_text: Optional[str],
    vocal_volume: float,
    vocal_intervals: Optional[List[Dict[str, Any]]],
    fx_intervals: Optional[List[Dict[str, Any]]],
    emoji_intervals: Optional[List[Dict[str, Any]]],
    num_lines: int,
    video_quality: str,
    use_cover_bg: bool,
    use_video_bg: bool,
    visual_effects: str,
    edge_color_mode: str,
    font_size_mode: str,
    highlight_color: str,
    dual_audio_mp4: bool = True,
    watermark_text: Optional[str] = None,
    export_dir: Optional[str] = None,
):
    reset_cancel()

    def update_progress(msg: str, frac: float):
        ws_manager.broadcast_threadsafe({
            "type": "progress",
            "fraction": frac,
            "message": msg,
            "stage": "rebuilding",
        })

    try:
        update_progress("Пересборка видео из сохраненного состояния...", 0.10)

        # Background resolution logic:
        # If use_cover_bg is requested, background must be None so create_cover_background
        # and album art card overlay are active (never overridden by lingering custom_bg).
        if use_cover_bg:
            bg_param = None
        elif use_video_bg and state_data.get("video_bg") and Path(state_data["video_bg"]).exists():
            bg_param = Path(state_data["video_bg"])
        else:
            custom_bg = state_data.get("custom_bg")
            bg_param = Path(custom_bg) if custom_bg and Path(custom_bg).exists() else None

        # Ensure cover art exists for cover mode
        cover_img_path = state_data.get("cover_image")
        if not cover_img_path or not Path(cover_img_path).exists():
            resolved_cover = ensure_project_cover(title, WORK_DIR)
            if resolved_cover and resolved_cover.exists():
                state_data["cover_image"] = str(resolved_cover)
                state_data["cover_edge_colors"] = extract_cover_edge_colors(resolved_cover)

        final_video, _mixed_audio, updated_editor_text = render_from_state(
            state_data=state_data,
            output_dir=OUTPUT_DIR,
            editor_text=editor_text or state_data.get("editor_text"),
            vocal_volume=vocal_volume,
            vocal_intervals=vocal_intervals if vocal_intervals is not None else state_data.get("vocal_intervals"),
            fx_intervals=fx_intervals if fx_intervals is not None else state_data.get("fx_intervals"),
            emoji_intervals=emoji_intervals if emoji_intervals is not None else state_data.get("emoji_intervals"),
            num_lines=num_lines,
            background=bg_param,
            use_cover_bg=use_cover_bg,
            use_video_bg=use_video_bg,
            visual_effects=visual_effects,
            edge_color_mode=edge_color_mode,
            font_size_mode=font_size_mode,
            highlight_color=highlight_color,
            video_quality=video_quality,
            dual_audio_mp4=dual_audio_mp4,
            watermark_text=watermark_text,
            progress_callback=update_progress,
        )

        exported_path: Optional[str] = None
        target_dir: Optional[Path] = None
        if export_dir:
            try:
                target_dir = Path(export_dir).resolve()
                target_dir.mkdir(parents=True, exist_ok=True)
                target_video = target_dir / final_video.name
                shutil.copy2(final_video, target_video)
                ass_file = OUTPUT_DIR / f"{title}_karaoke.ass"
                if ass_file.exists():
                    shutil.copy2(ass_file, target_dir / ass_file.name)
                exported_path = str(target_video)
                state_data["export_dir"] = str(target_dir)
            except Exception as e:
                print(f"[Rebuild] Warning: Could not copy to export_dir: {e}")

        # Persist final state back to disk so reloading on frontend never loses fx_intervals or vocal_intervals
        state_data["editor_text"] = updated_editor_text
        state_data["lines"] = editor_text_to_lines(updated_editor_text, original_lines=state_data.get("lines", []))
        state_data["has_video"] = True
        state_file = WORK_DIR / f"{title}_state.json"
        state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

        save_msg = f" и сохранен в:\n{target_dir.name}" if target_dir else ""
        ws_manager.broadcast_threadsafe({
            "type": "completed",
            "action": "rebuild",
            "title": title,
            "video_path": str(final_video),
            "exported_path": exported_path,
            "export_dir": str(target_dir) if target_dir else str(OUTPUT_DIR.resolve()),
            "message": f"🎬 Видео для '{title}' успешно обновлено{save_msg}!",
        })
    except GenerationCancelledError:
        ws_manager.broadcast_threadsafe({
            "type": "cancelled",
            "message": "🛑 Пересборка видео отменена пользователем.",
        })
    except Exception as e:
        ws_manager.broadcast_threadsafe({
            "type": "error",
            "message": f"Ошибка сборки видео: {e}",
        })


@router.post("/pipeline/rebuild")
def start_rebuild(payload: RebuildRequest) -> Dict[str, Any]:
    state_file = WORK_DIR / f"{payload.title}_state.json"
    if not state_file.exists():
        raise HTTPException(status_code=404, detail="Проект не найден.")

    state_data = json.loads(state_file.read_text(encoding="utf-8"))

    # Immediately synchronize all timeline and modal parameters into state_data
    if payload.fx_intervals is not None:
        state_data["fx_intervals"] = payload.fx_intervals
    if payload.vocal_intervals is not None:
        state_data["vocal_intervals"] = payload.vocal_intervals
    if payload.emoji_intervals is not None:
        state_data["emoji_intervals"] = payload.emoji_intervals
    if payload.editor_text is not None:
        state_data["editor_text"] = payload.editor_text
        state_data["lines"] = editor_text_to_lines(payload.editor_text, original_lines=state_data.get("lines", []))
    state_data["num_lines"] = payload.num_lines
    state_data["video_quality"] = payload.video_quality
    state_data["visual_effects"] = payload.visual_effects
    state_data["edge_color_mode"] = payload.edge_color_mode
    state_data["font_size_mode"] = payload.font_size_mode
    state_data["highlight_color"] = payload.highlight_color
    state_data["dual_audio_mp4"] = payload.dual_audio_mp4
    state_data["use_cover_bg"] = payload.use_cover_bg
    state_data["use_video_bg"] = payload.use_video_bg
    if payload.watermark_text is not None:
        state_data["watermark_text"] = payload.watermark_text

    # Write to disk before kicking off thread
    state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")

    t = threading.Thread(
        target=_run_rebuild_task,
        args=(
            payload.title,
            state_data,
            payload.editor_text,
            payload.vocal_volume,
            payload.vocal_intervals,
            payload.fx_intervals,
            payload.emoji_intervals,
            payload.num_lines,
            payload.video_quality,
            payload.use_cover_bg,
            payload.use_video_bg,
            payload.visual_effects,
            payload.edge_color_mode,
            payload.font_size_mode,
            payload.highlight_color,
            payload.dual_audio_mp4,
            payload.watermark_text,
            payload.export_dir,
        ),
        daemon=True,
    )
    t.start()
    return {"status": "started", "title": payload.title}


@router.post("/projects/{title}/export-dj-pack")
def build_project_dj_pack(title: str, payload: DjExportRequest) -> Dict[str, Any]:
    """Builds the professional DJ Master Pack (.zip) and KaraFun/EnCore (.kfn) file on demand."""
    state_file = WORK_DIR / f"{title}_state.json"
    if not state_file.exists():
        raise HTTPException(status_code=404, detail=f"Проект '{title}' не найден.")

    from karaoke.pro_exporter import export_dj_master_pack

    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    dj_zip_path, kfn_path = export_dj_master_pack(
        state_data=state_data,
        output_dir=OUTPUT_DIR,
        editor_text=payload.editor_text or state_data.get("editor_text"),
        vocal_volume=payload.vocal_volume,
        vocal_intervals=payload.vocal_intervals if payload.vocal_intervals is not None else state_data.get("vocal_intervals"),
    )

    exported_dir: Optional[str] = None
    if payload.export_dir:
        try:
            target_dir = Path(payload.export_dir).resolve()
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dj_zip_path, target_dir / dj_zip_path.name)
            shutil.copy2(kfn_path, target_dir / kfn_path.name)
            exported_dir = str(target_dir)
        except Exception as e:
            print(f"[DJ Pack] Warning: Could not copy to export_dir: {e}")

    return {
        "status": "ok",
        "title": title,
        "dj_pack_url": f"/api/media/{title}/dj-pack",
        "kfn_url": f"/api/media/{title}/kfn",
        "dj_pack_filename": dj_zip_path.name,
        "kfn_filename": kfn_path.name,
        "exported_dir": exported_dir,
    }


@router.get("/media/{title}/dj-pack")
def download_dj_pack(title: str):
    zip_path = OUTPUT_DIR / f"{title}_DJ_Pack.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="DJ-пак еще не собран.")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=zip_path.name,
    )


@router.get("/media/{title}/kfn")
def download_kfn_file(title: str):
    kfn_path = OUTPUT_DIR / f"{title}.kfn"
    if not kfn_path.exists():
        raise HTTPException(status_code=404, detail="KFN-файл еще не собран.")
    return FileResponse(
        kfn_path,
        media_type="application/octet-stream",
        filename=kfn_path.name,
    )


# Media streaming routes with range request support
@router.get("/media/{title}/video")
def get_video_stream(title: str):
    video_path = OUTPUT_DIR / f"{title}_karaoke.mp4"
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Видеофайл не найден.")
    return FileResponse(
        video_path,
        media_type="video/mp4",
        filename=video_path.name,
    )


@router.get("/media/{title}/vocals")
def get_vocals_stream(title: str):
    state_file = WORK_DIR / f"{title}_state.json"
    if state_file.exists():
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
        p = state_data.get("vocals_wav")
        if p and Path(p).exists():
            return FileResponse(Path(p), media_type="audio/wav")

    # Fallback to standard location
    candidates = list(WORK_DIR.glob(f"*{title}*vocals*.wav"))
    if candidates and candidates[0].exists():
        return FileResponse(candidates[0], media_type="audio/wav")
    raise HTTPException(status_code=404, detail="Дорожка вокала не найдена.")


@router.get("/media/{title}/instrumental")
def get_instrumental_stream(title: str):
    state_file = WORK_DIR / f"{title}_state.json"
    if state_file.exists():
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
        p = state_data.get("no_vocals_wav")
        if p and Path(p).exists():
            return FileResponse(Path(p), media_type="audio/wav")

    candidates = list(WORK_DIR.glob(f"*{title}*no_vocals*.wav"))
    if candidates and candidates[0].exists():
        return FileResponse(candidates[0], media_type="audio/wav")
    raise HTTPException(status_code=404, detail="Инструментальная дорожка не найдена.")


@router.get("/media/{title}/cover")
def get_cover_image(title: str):
    cover_file = WORK_DIR / f"{title}_cover.png"
    if cover_file.exists():
        return FileResponse(cover_file, media_type="image/png")

    state_file = WORK_DIR / f"{title}_state.json"
    if state_file.exists():
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
        p = state_data.get("cover_image")
        if p and Path(p).exists():
            return FileResponse(Path(p), media_type="image/png")

    default_bg = OUTPUT_DIR / "default_bg.png"
    if default_bg.exists():
        return FileResponse(default_bg, media_type="image/png")

    raise HTTPException(status_code=404, detail="Обложка не найдена.")


@router.get("/media/{title}/slice-preview")
def get_slice_preview_video(title: str):
    preview_file = WORK_DIR / f"{title}_slice_preview.mp4"
    if preview_file.exists():
        return FileResponse(preview_file, media_type="video/mp4")
    raise HTTPException(status_code=404, detail="Превью видео не найдено.")
