import re
import torch
from pathlib import Path
from typing import Dict, Any, Optional
import whisper_timestamped as whisper
from karaoke.aligner import refine_word_timestamps, align_russian_ctc_on_segments
from karaoke.cancel_manager import check_cancelled, GenerationCancelledError

WHISPER_MODELS = [
    "large-v3-turbo",                     # Рекомендуется: быстрая и точная для русского, песен, оперы (по умолчанию)
    "bond005/whisper-podlodka-turbo",     # Русский fine-tune Whisper Turbo (Иван Бондаренко)
    "antony66/whisper-large-v3-russian",  # Русский fine-tune Large-v3 (Common Voice RU, речь)
    "large-v3",                           # Максимальная базовая модель OpenAI
    "medium",                             # Средняя модель
    "small",                              # Легкая быстрая модель
]

HALLUCINATION_PATTERNS = [
    re.compile(r"субтитр[ыа-я]*\s+(сделал|создал|подготовил|перевел|добавил)", re.I),
    re.compile(r"dimatorzok|дима\s*торзок", re.I),
    re.compile(r"редактор[а-я]*\s+субтитр", re.I),
    re.compile(r"перевод\s+(и\s+озвучка|на\s+русский|субтитр)", re.I),
    re.compile(r"amara\.org", re.I),
    re.compile(r"продолжение\s+следует", re.I),
    re.compile(r"подписывайтесь\s+на\s+канал", re.I),
    re.compile(r"ставьте\s+лайк", re.I),
]


def is_hallucinated_segment(text: str) -> bool:
    """Detects common YouTube subtitle artifacts and repetitive operatic vocalise loops."""
    if not text or not text.strip():
        return True
    for pat in HALLUCINATION_PATTERNS:
        if pat.search(text):
            return True
    # Repetitive single character loops (e.g. "и-и-и-и-и..." or "а-а-а...")
    cleaned = re.sub(r"[\s\-–—,.]+", "", text)
    if re.search(r"(\w)\1{5,}", cleaned):
        return True
    # Repetitive short syllable loops
    tokens = [t for t in re.split(r"[\s\-–—,.]+", text) if t]
    if len(tokens) >= 6:
        first = tokens[0].lower()
        if sum(1 for t in tokens if t.lower() == first) / len(tokens) > 0.8:
            return True
    return False


def transcribe_vocals(
    vocals_path: Path,
    model_size: str = "large-v3-turbo",
    language: Optional[str] = "ru",
    device: Optional[str] = None,
    initial_prompt: Optional[str] = None,
    use_ctc_align: bool = True,
    condition_on_previous_text: bool = False,
    vad: Optional[str] = "auditok",
) -> Dict[str, Any]:
    """
    Transcribes vocals and extracts accurate word-level timestamps optimized for Russian/Cyrillic.
    - Disables detect_disfluencies (no [*] artifacts).
    - Uses VAD ('auditok') to prevent words from stretching across instrumental intros/solos.
    - Disables condition_on_previous_text by default to prevent repetitive hallucination cascades.
    - Calibrates word boundaries against the actual vocal RMS energy envelope of vocals.wav.
    """
    check_cancelled()
    if device is None:
        if torch.cuda.is_available():
            device = "cuda"
        else:
            # whisper-timestamped uses sparse tensors for DTW alignment unsupported on PyTorch SparseMPS
            device = "cpu"

    if not language or not language.strip():
        language = "ru"

    # Prefer native "openai-whisper" backend for all models (including HF fine-tunes).
    backend = "openai-whisper"

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
            print(f"[Karaoke] Предупреждение: ошибка с backend={backend} ({e2}), пробуем transformers...")
            try:
                backend = "transformers"
                model = whisper.load_model(model_size, device="cpu", backend=backend)
            except Exception as e3:
                check_cancelled()
                print(f"[Karaoke] Ошибка загрузки модели '{model_size}' ({e3}). Откат на проверенную 'large-v3-turbo'...")
                model_size = "large-v3-turbo"
                backend = "openai-whisper"
                device = "cpu"
                model = whisper.load_model("large-v3-turbo", device="cpu", backend="openai-whisper")

    check_cancelled()
    audio = whisper.load_audio(str(vocals_path))
    print(f"[Karaoke] Распознавание вокала и таймингов (язык={language})...")

    effective_vad = vad if vad and vad.lower() != "none" else None

    transcribe_kwargs: Dict[str, Any] = {
        "model": model,
        "audio": audio,
        "language": language,
        "verbose": False,
        "detect_disfluencies": False,
        "vad": effective_vad,
        "condition_on_previous_text": bool(condition_on_previous_text),
        "compression_ratio_threshold": 3.2,
    }

    if initial_prompt and initial_prompt.strip():
        # Provide natural lyrics excerpt to guide vocabulary and casing without inducing repetitive loops
        prompt_words = initial_prompt.strip().split()
        if prompt_words:
            transcribe_kwargs["initial_prompt"] = " ".join(prompt_words[:120])

    try:
        result = whisper.transcribe(**transcribe_kwargs)
    except GenerationCancelledError:
        raise
    except Exception as e:
        check_cancelled()
        print(f"[Karaoke] Предупреждение при распознавании с VAD ({e}), повтор на CPU без VAD...")
        transcribe_kwargs.pop("vad", None)
        transcribe_kwargs["audio"] = whisper.load_audio(str(vocals_path))
        if device != "cpu":
            device = "cpu"
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

    # Filter hallucinated subtitle lines and repetitive operatic vocalise loops
    raw_segments = result.get("segments", [])
    filtered_segments = []
    for s in raw_segments:
        s_text = s.get("text", "").strip()
        if is_hallucinated_segment(s_text):
            continue
        filtered_segments.append(s)
    result["segments"] = filtered_segments

    # Calibrate word timestamps with vocal energy envelope and anti-squash syllable balancing
    refined_segments = refine_word_timestamps(result, vocals_path=vocals_path)

    # Multilingual / Cyrillic CTC character & syllable-level forced alignment pass
    if use_ctc_align:
        refined_segments = align_russian_ctc_on_segments(refined_segments, vocals_path)

    result["segments"] = refined_segments
    return result
