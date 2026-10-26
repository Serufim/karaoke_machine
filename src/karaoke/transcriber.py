import torch
from pathlib import Path
from typing import Dict, Any, Optional
import whisper_timestamped as whisper
from karaoke.aligner import refine_word_timestamps, align_russian_ctc_on_segments
from karaoke.cancel_manager import check_cancelled, GenerationCancelledError

WHISPER_MODELS = [
    "large-v3-turbo",                     # Рекомендуется: быстрая и точная для русского (по умолчанию)
    "bond005/whisper-podlodka-turbo",     # Русский fine-tune Whisper Turbo (Иван Бондаренко)
    "antony66/whisper-large-v3-russian",  # Русский fine-tune Large-v3 (Common Voice RU)
    "large-v3",                           # Максимальная базовая модель OpenAI
    "medium",                             # Средняя модель
    "small",                              # Легкая быстрая модель
]


def transcribe_vocals(
    vocals_path: Path,
    model_size: str = "large-v3-turbo",
    language: Optional[str] = "ru",
    device: Optional[str] = None,
    initial_prompt: Optional[str] = None,
    use_ctc_align: bool = False,
) -> Dict[str, Any]:
    """
    Transcribes vocals and extracts accurate word-level timestamps optimized for Russian/Cyrillic.
    - Disables detect_disfluencies (no [*] artifacts).
    - Uses VAD ('auditok') to prevent words from stretching across instrumental intros/solos.
    - Calibrates word boundaries against the actual vocal RMS energy envelope of vocals.wav.
    """
    check_cancelled()
    if device is None:
        if torch.backends.mps.is_available() and torch.backends.mps.is_built():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"

    if not language or not language.strip():
        language = "ru"

    is_hf_model = "/" in model_size
    backend = "transformers" if is_hf_model else "openai-whisper"

    print(f"[Karaoke] Загрузка модели '{model_size}' (backend={backend}, device={device})...")
    try:
        model = whisper.load_model(model_size, device=device, backend=backend)
    except Exception as e:
        check_cancelled()
        print(f"[Karaoke] Предупреждение: не удалось загрузить '{model_size}' на {device} ({e}), пробуем CPU...")
        try:
            device = "cpu"
            model = whisper.load_model(model_size, device="cpu", backend=backend)
        except Exception as e2:
            check_cancelled()
            print(f"[Karaoke] Ошибка загрузки модели '{model_size}' ({e2}). Откат на проверенную 'large-v3-turbo'...")
            model_size = "large-v3-turbo"
            backend = "openai-whisper"
            device = "cpu"
            model = whisper.load_model("large-v3-turbo", device="cpu", backend="openai-whisper")

    check_cancelled()
    audio = whisper.load_audio(str(vocals_path))
    print(f"[Karaoke] Распознавание вокала и таймингов (язык={language})...")

    transcribe_kwargs: Dict[str, Any] = {
        "model": model,
        "audio": audio,
        "language": language,
        "verbose": False,
        "detect_disfluencies": False,
        "vad": "auditok",
        "condition_on_previous_text": False,
    }

    if initial_prompt and initial_prompt.strip():
        # Pass reference lyrics vocabulary as initial_prompt to guide spelling and slang
        prompt_clean = " ".join(initial_prompt.strip().split()[:120])
        transcribe_kwargs["initial_prompt"] = prompt_clean

    try:
        result = whisper.transcribe(**transcribe_kwargs)
    except GenerationCancelledError:
        raise
    except Exception as e:
        check_cancelled()
        print(f"[Karaoke] Предупреждение при распознавании с VAD/MPS ({e}), повтор на CPU без VAD...")
        transcribe_kwargs.pop("vad", None)
        if device != "cpu":
            model = whisper.load_model(model_size, device="cpu", backend=backend)
            transcribe_kwargs["model"] = model
        result = whisper.transcribe(**transcribe_kwargs)

    check_cancelled()
    # Free Whisper model memory before alignment
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    elif device == "mps":
        torch.mps.empty_cache()

    # Calibrate word timestamps with vocal energy envelope and anti-squash syllable balancing
    refined_segments = refine_word_timestamps(result, vocals_path=vocals_path)

    # Optional Cyrillic Wav2Vec2 CTC character-level pass
    if use_ctc_align and language.lower().startswith("ru"):
        refined_segments = align_russian_ctc_on_segments(refined_segments, vocals_path, device="cpu")

    result["segments"] = refined_segments
    return result
