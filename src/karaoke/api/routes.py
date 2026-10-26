import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from karaoke.model_manager import (
    get_models_status_list,
    start_model_download_background,
    delete_model_cache,
    MODEL_CATALOG,
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
            progress_callback=update_progress,
        )

        update_progress("Сборка базового видео караоке...", 0.70)
        final_video, _mixed_audio, updated_editor_text = render_from_state(
            state_data=state_data,
            output_dir=OUTPUT_DIR,
            editor_text=state_data.get("editor_text"),
            vocal_volume=vocal_volume,
            num_lines=num_lines,
            video_quality=video_quality,
            use_cover_bg=True,
            use_video_bg=download_video,
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


@router.post("/pipeline/generate")
async def start_generate(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
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
):
    temp_upload_path = None
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
    else:
        raise HTTPException(status_code=400, detail="Загрузите файл или укажите ссылку на YouTube.")

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
        custom_bg = state_data.get("custom_bg")
        bg_param = Path(custom_bg) if custom_bg and Path(custom_bg).exists() else None

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
            progress_callback=update_progress,
        )

        ws_manager.broadcast_threadsafe({
            "type": "completed",
            "action": "rebuild",
            "title": title,
            "video_path": str(final_video),
            "message": f"🎬 Видео для '{title}' успешно обновлено!",
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
        ),
        daemon=True,
    )
    t.start()
    return {"status": "started", "title": payload.title}


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

    raise HTTPException(status_code=404, detail="Обложка не найдена.")
