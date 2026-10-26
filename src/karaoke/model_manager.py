"""
Model catalog and on-demand model manager for AI Karaoke Studio.
Provides model registry, resource requirements, status checking,
background downloading with progress updates, and cache cleanup.
"""

import os
import shutil
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from karaoke.config import CACHE_DIR, setup_isolated_environment

# Ensure isolated cache dirs are configured
setup_isolated_environment()

WHISPER_CACHE_DIR = CACHE_DIR / "whisper"
WHISPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ModelMetadata:
    id: str
    name: str
    type: str  # "whisper", "demucs", "aligner"
    description: str
    download_size_mb: int
    min_vram_gb: float
    min_ram_gb: float
    recommended_for: str
    is_default: bool = False
    is_hf: bool = False


# Comprehensive registry of supported models
MODEL_CATALOG: Dict[str, ModelMetadata] = {
    # Whisper models
    "large-v3-turbo": ModelMetadata(
        id="large-v3-turbo",
        name="Whisper Large-v3 Turbo",
        type="whisper",
        description="Официальная быстрая модель OpenAI. Высокая точность при отличной скорости.",
        download_size_mb=1600,
        min_vram_gb=4.0,
        min_ram_gb=6.0,
        recommended_for="Рекомендуется для большинства современных ПК и Mac",
        is_default=True,
    ),
    "bond005/whisper-podlodka-turbo": ModelMetadata(
        id="bond005/whisper-podlodka-turbo",
        name="Whisper Podlodka Russian Turbo",
        type="whisper",
        description="Русскоязычный fine-tune на базе Turbo от Ивана Бондаренко. Отлично понимает современный сленг.",
        download_size_mb=1600,
        min_vram_gb=4.0,
        min_ram_gb=6.0,
        recommended_for="Русскоязычный рэп, инди и современная музыка",
        is_hf=True,
    ),
    "antony66/whisper-large-v3-russian": ModelMetadata(
        id="antony66/whisper-large-v3-russian",
        name="Whisper Large-v3 Russian (Common Voice)",
        type="whisper",
        description="Специализированный русский fine-tune. Максимальная словарная точность для сложного вокала.",
        download_size_mb=3100,
        min_vram_gb=6.0,
        min_ram_gb=8.0,
        recommended_for="Сложный и неразборчивый русский вокал",
        is_hf=True,
    ),
    "large-v3": ModelMetadata(
        id="large-v3",
        name="Whisper Large-v3",
        type="whisper",
        description="Полноразмерная модель OpenAI. Высокая точность распознавания любых языков.",
        download_size_mb=3100,
        min_vram_gb=6.0,
        min_ram_gb=8.0,
        recommended_for="Мощные ПК с 8+ GB VRAM",
    ),
    "medium": ModelMetadata(
        id="medium",
        name="Whisper Medium",
        type="whisper",
        description="Сбалансированная модель между качеством и потреблением ресурсов.",
        download_size_mb=1500,
        min_vram_gb=3.0,
        min_ram_gb=5.0,
        recommended_for="Средние ПК",
    ),
    "small": ModelMetadata(
        id="small",
        name="Whisper Small",
        type="whisper",
        description="Компактная быстрая модель. Работает даже на бюджетных ноутбуках и встроенной графике.",
        download_size_mb=460,
        min_vram_gb=2.0,
        min_ram_gb=3.0,
        recommended_for="Бюджетные ПК и режим CPU",
    ),
    "base": ModelMetadata(
        id="base",
        name="Whisper Base",
        type="whisper",
        description="Минимальная ультра-легкая модель для мгновенного черновика.",
        download_size_mb=140,
        min_vram_gb=1.0,
        min_ram_gb=2.0,
        recommended_for="Слабые компьютеры и быстрые тесты",
    ),

    # Demucs models
    "htdemucs": ModelMetadata(
        id="htdemucs",
        name="Hybrid Transformer Demucs",
        type="demucs",
        description="Стандартная модель разделения вокала и музыки от Meta. Быстрая и стабильная.",
        download_size_mb=80,
        min_vram_gb=2.0,
        min_ram_gb=4.0,
        recommended_for="Быстрое разделение (рекомендуется по умолчанию)",
        is_default=True,
    ),
    "htdemucs_ft": ModelMetadata(
        id="htdemucs_ft",
        name="HT Demucs Fine-Tuned (4x Ensemble)",
        type="demucs",
        description="4x ансамбль нейросетей Demucs. Студийная чистота вокала и минимальное проникновение бита.",
        download_size_mb=320,
        min_vram_gb=4.0,
        min_ram_gb=6.0,
        recommended_for="Максимальное качество караоке-минуса",
    ),
    "mdx_extra": ModelMetadata(
        id="mdx_extra",
        name="MDX-Net Extra",
        type="demucs",
        description="Альтернативная архитектура разделения вокала с акцентом на сохранение высоких частот.",
        download_size_mb=160,
        min_vram_gb=3.0,
        min_ram_gb=4.0,
        recommended_for="Рок и электронная музыка",
    ),

    # Aligner models
    "jonatasgrosman/wav2vec2-large-xlsr-53-russian": ModelMetadata(
        id="jonatasgrosman/wav2vec2-large-xlsr-53-russian",
        name="Wav2Vec2 Russian CTC Aligner",
        type="aligner",
        description="Фонетический выравниватель букв и слогов для русского языка. Обеспечивает караоке-подсветку без задержек.",
        download_size_mb=1200,
        min_vram_gb=3.0,
        min_ram_gb=4.0,
        recommended_for="Идеальный пословный тайминг для русских песен",
        is_hf=True,
    ),
}

# In-memory tracking of active downloads
_active_downloads: Dict[str, Dict[str, Any]] = {}
_download_lock = threading.Lock()


def get_model_cache_path(model_id: str) -> Optional[Path]:
    """Finds existing cache directory or file for a model."""
    meta = MODEL_CATALOG.get(model_id)
    if not meta:
        return None

    if meta.is_hf:
        hf_hub = CACHE_DIR / "huggingface" / "hub"
        repo_dir_name = f"models--{model_id.replace('/', '--')}"
        target = hf_hub / repo_dir_name
        if target.exists() and any(target.iterdir()):
            return target
        # Also check default user HF cache if present
        default_hf = Path.home() / ".cache" / "huggingface" / "hub" / repo_dir_name
        if default_hf.exists() and any(default_hf.iterdir()):
            return default_hf
        return None

    if meta.type == "whisper":
        # Whisper stores .pt files in WHISPER_CACHE_DIR or ~/.cache/whisper
        pt_name = f"{model_id}.pt"
        for check_dir in [WHISPER_CACHE_DIR, Path.home() / ".cache" / "whisper"]:
            cand = check_dir / pt_name
            if cand.exists() and cand.stat().st_size > 1024 * 1024:
                return cand
        return None

    if meta.type == "demucs":
        # Demucs models live in torch hub checkpoints or torchaudio
        torch_hub = CACHE_DIR / "torch" / "hub" / "checkpoints"
        default_hub = Path.home() / ".cache" / "torch" / "hub" / "checkpoints"
        for check_dir in [torch_hub, default_hub]:
            if check_dir.exists():
                for p in check_dir.glob(f"*{model_id}*"):
                    if p.is_file() and p.stat().st_size > 1024 * 1024:
                        return p
        return None

    return None


def is_model_downloaded(model_id: str) -> bool:
    """Returns True if the model is locally cached and ready for inference."""
    path = get_model_cache_path(model_id)
    return path is not None


def get_model_size_on_disk_mb(model_id: str) -> Optional[float]:
    """Computes exact size in MB on disk for downloaded model."""
    path = get_model_cache_path(model_id)
    if not path or not path.exists():
        return None

    if path.is_file():
        return round(path.stat().st_size / (1024 * 1024), 1)

    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return round(total / (1024 * 1024), 1)


def get_models_status_list() -> List[Dict[str, Any]]:
    """Returns full catalog of models enriched with local status, size, and download state."""
    result = []
    with _download_lock:
        active = dict(_active_downloads)

    for mid, meta in MODEL_CATALOG.items():
        data = asdict(meta)
        downloaded = is_model_downloaded(mid)
        size_on_disk = get_model_size_on_disk_mb(mid) if downloaded else None

        active_info = active.get(mid)
        status = "ready" if downloaded else "not_downloaded"
        progress = 100 if downloaded else 0

        if active_info:
            status = active_info.get("status", "downloading")
            progress = active_info.get("progress", 0)

        data.update({
            "is_downloaded": downloaded,
            "size_on_disk_mb": size_on_disk,
            "status": status,
            "progress": progress,
        })
        result.append(data)

    return result


def delete_model_cache(model_id: str) -> bool:
    """Deletes cached model files to reclaim disk space."""
    path = get_model_cache_path(model_id)
    if not path or not path.exists():
        return False

    try:
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        return True
    except Exception as e:
        print(f"[ModelManager] Error deleting {model_id}: {e}")
        return False


def download_model(
    model_id: str,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """
    Downloads model weights into the isolated cache.
    Executes synchronously; call inside a thread for non-blocking execution.
    """
    meta = MODEL_CATALOG.get(model_id)
    if not meta:
        raise ValueError(f"Unknown model_id: {model_id}")

    with _download_lock:
        _active_downloads[model_id] = {
            "status": "downloading",
            "progress": 5,
            "message": "Инициализация загрузки...",
        }

    def _notify(progress: int, message: str, status: str = "downloading"):
        with _download_lock:
            _active_downloads[model_id] = {
                "status": status,
                "progress": progress,
                "message": message,
            }
        if progress_callback:
            progress_callback({
                "model_id": model_id,
                "status": status,
                "progress": progress,
                "message": message,
            })

    try:
        _notify(10, "Подключение к репозиторию...")

        if meta.is_hf:
            from transformers import AutoModel, AutoTokenizer
            _notify(30, "Загрузка токенизатора и конфигурации...")
            AutoTokenizer.from_pretrained(model_id)
            _notify(50, "Загрузка весов нейросети...")
            AutoModel.from_pretrained(model_id)
            _notify(100, "Модель успешно загружена", status="ready")

        elif meta.type == "whisper":
            import whisper_timestamped as whisper
            _notify(20, f"Загрузка весов Whisper ({model_id})...")
            # OpenAI whisper loads into download_root if specified
            whisper.load_model(model_id, device="cpu", download_root=str(WHISPER_CACHE_DIR))
            _notify(100, "Модель успешно загружена", status="ready")

        elif meta.type == "demucs":
            import demucs.pretrained
            _notify(25, f"Загрузка архитектуры Demucs ({model_id})...")
            demucs.pretrained.get_model(model_id)
            _notify(100, "Модель успешно загружена", status="ready")

    except Exception as e:
        _notify(0, f"Ошибка загрузки: {str(e)}", status="error")
        raise
    finally:
        with _download_lock:
            _active_downloads.pop(model_id, None)


def start_model_download_background(
    model_id: str,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> threading.Thread:
    """Launches model download in a background daemon thread."""
    t = threading.Thread(
        target=download_model,
        args=(model_id, progress_callback),
        daemon=True,
    )
    t.start()
    return t
