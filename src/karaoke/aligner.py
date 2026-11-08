import re
import math
import difflib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import soundfile as sf

# Russian & English vowels for syllable estimation
VOWELS = set("аеёиоуыэюяАЕЁИОУЫЭЮЯaeiouyAEIOUY")

# Russian prepositions, conjunctions, and particles that should never dangle at the end of a line
RUSSIAN_NO_DANGLE = {
    "в", "во", "на", "с", "со", "к", "ко", "у", "о", "об", "обо", "от", "ото",
    "до", "за", "из", "изо", "по", "под", "подо", "над", "пред", "при", "про",
    "без", "безо", "для", "меж", "между", "через", "сквозь", "и", "а", "но",
    "да", "или", "либо", "не", "ни", "как", "что", "чтоб", "чтобы", "когда",
    "если", "лишь", "только", "вот", "ведь", "мой", "твой", "свой", "наш", "ваш",
    "его", "ее", "её", "их", "этот", "эта", "это", "эти", "тот", "та", "то", "те"
}

# Regex patterns for cleaning web watermarks, metadata, and structural tags from reference lyrics
METADATA_LINE_RE = re.compile(
    r'(?:источник\s*:|взят[оа]?\s+с\s+сайта|текст\s+(?:песни\s+)?(?:добавил|взят|прислал)|правообладател|авторские\s+права|www\.[a-z0-9]|https?://|[a-z0-9_-]+\.(?:ru|com|net|org|io|me|fm|kz|by)\b)',
    re.IGNORECASE,
)

STRUCTURE_LINE_RE = re.compile(
    r'^\s*(?:\[|\()?\s*(?:куплет|припев|интро|аутро|бридж|хук|скит|предприпев|verse|chorus|intro|outro|bridge|hook|drop|pre-chorus)\s*\d*\s*(?:\]|\))?\s*:?\s*$',
    re.IGNORECASE,
)

REPEAT_STANDALONE_RE = re.compile(
    r'^\s*(?:\[|\()?\s*(?:[xх]\s*\d+|\d+\s*раза?)\s*(?:\]|\))?\s*$',
    re.IGNORECASE,
)

REPEAT_INLINE_RE = re.compile(
    r'\s*(?:\[|\()?\s*(?:[xх]\s*\d+|\d+\s*раза?)\s*(?:\]|\))?\s*$',
    re.IGNORECASE,
)


def sanitize_reference_lyrics(text_or_lines: Any) -> List[str]:
    """
    Cleans raw reference lyrics by stripping:
    - Web aggregator watermarks and metadata ('Источник: txtsong.ru', URLs, etc.)
    - Structural markers ('[Куплет 1]', '[Припев]', '(Интро)', 'Куплет 1:', etc.)
    - Standalone or trailing repetition annotations ('(х2)', '(x2)', '(2 раза)')
    - Decorative delimiters ('---', '***', '===')
    """
    if isinstance(text_or_lines, str):
        raw_lines = text_or_lines.splitlines()
    elif isinstance(text_or_lines, (list, tuple)):
        raw_lines = list(text_or_lines)
    else:
        return []

    result = []
    for raw in raw_lines:
        line = str(raw).strip()
        if not line or re.match(r'^[-=*_#\s]+$', line):
            continue
        if METADATA_LINE_RE.search(line):
            continue
        if STRUCTURE_LINE_RE.match(line):
            continue
        if REPEAT_STANDALONE_RE.match(line):
            continue
        clean = REPEAT_INLINE_RE.sub('', line).strip()
        if clean:
            result.append(clean)
    return result


def count_syllables(word: str) -> int:
    """Counts syllables in a Russian/English word based on vowel count (min 1)."""
    cleaned = re.sub(r"[^а-яёА-ЯЁa-zA-Z]", "", word)
    if not cleaned:
        return 1
    v_count = sum(1 for ch in cleaned if ch in VOWELS)
    return max(1, v_count)


def clean_word_token(text: str) -> str:
    """Removes disfluency markers [*] and ASS control characters."""
    text = text.replace("[*]", "").replace("{", "").replace("}", "").strip()
    return text


def compute_vocal_rms_envelope(
    vocals_path: Optional[Path],
    hop_s: float = 0.01
) -> Tuple[Optional[np.ndarray], float]:
    """
    Computes a 10ms RMS energy envelope from vocals.wav to detect real vocal onsets/offsets.
    Returns (rms_array, hop_s).
    """
    if vocals_path is None or not Path(vocals_path).exists():
        return None, hop_s

    try:
        data, sr = sf.read(str(vocals_path), dtype="float32", always_2d=True)
        mono = np.mean(data, axis=1)
        hop_samples = max(1, int(round(sr * hop_s)))
        n_frames = len(mono) // hop_samples
        if n_frames == 0:
            return None, hop_s
        frames = mono[: n_frames * hop_samples].reshape(n_frames, hop_samples)
        rms = np.sqrt(np.mean(frames ** 2, axis=1))
        return rms, hop_s
    except Exception as e:
        print(f"[Karaoke] Warning: Could not compute vocal RMS envelope: {e}")
        return None, hop_s


def find_first_vocal_onset(
    rms: Optional[np.ndarray],
    hop_s: float,
    threshold_ratio: float = 0.08,
    min_consecutive_frames: int = 14,
) -> Optional[float]:
    """
    Finds the global first vocal onset in the isolated vocals audio.
    Used to prevent hallucinated Whisper words or reference lyrics from appearing
    during an instrumental intro before the singer actually starts singing.
    Filters out isolated transient bleed pops (<150ms) followed by extended silence (>2.0s).
    """
    if rms is None or len(rms) == 0:
        return None
    global_p90 = float(np.percentile(rms, 90)) if len(rms) > 0 else 0.0
    if global_p90 < 0.005:
        return None
    thresh = max(0.008, global_p90 * threshold_ratio)
    active = rms > thresh
    post_silence_frames = int(2.0 / hop_s) if hop_s > 0 else 200
    for idx in range(len(active) - (min_consecutive_frames - 1)):
        if all(active[idx + k] for k in range(min_consecutive_frames)):
            # Check if this is an isolated bleed artifact before long intro silence
            post_window = active[idx + min_consecutive_frames : idx + min_consecutive_frames + post_silence_frames]
            if len(post_window) >= post_silence_frames and not any(post_window):
                continue
            onset = max(0.0, idx * hop_s - 0.07)
            return round(onset, 2)
    return None


def find_vocal_onset(
    rms: Optional[np.ndarray],
    hop_s: float,
    search_start: float,
    search_end: float,
    threshold_ratio: float = 0.08,
    fallback: Optional[float] = None,
) -> float:
    """
    Finds the actual start of singing within [search_start, search_end] using the vocal RMS envelope.
    Prevents the first word of a phrase from stretching back across an instrumental intro/solo.
    """
    default_ret = fallback if fallback is not None else search_start
    if rms is None or len(rms) == 0 or search_end <= search_start + 0.35:
        return default_ret

    i_start = max(0, int(search_start / hop_s))
    i_end = min(len(rms), int(search_end / hop_s))
    if i_end <= i_start + 5:
        return default_ret

    window = rms[i_start:i_end]
    peak = float(np.percentile(window, 95)) if len(window) > 0 else 0.0
    global_p90 = float(np.percentile(rms, 90)) if len(rms) > 0 else 0.0
    thresh = max(0.008, min(peak * 0.18, global_p90 * threshold_ratio))

    # Require at least 4 consecutive frames (40ms) above threshold for genuine vocal onset
    active = window > thresh
    for idx in range(len(active) - 3):
        if active[idx] and active[idx + 1] and active[idx + 2]:
            # Give 70ms lead-in for unvoiced consonants (п, т, к, с, ш, х)
            onset_time = (i_start + idx) * hop_s - 0.07
            return max(search_start, min(search_end - 0.15, onset_time))

    return default_ret


def find_vocal_offset(
    rms: Optional[np.ndarray],
    hop_s: float,
    search_start: float,
    search_end: float,
    threshold_ratio: float = 0.08,
    min_silence_s: float = 0.5,
) -> float:
    """
    Finds the actual end of singing within [search_start, search_end] using the vocal RMS envelope.
    Prevents the trailing word of a phrase from stretching forward across an instrumental pause or solo.
    """
    if rms is None or len(rms) == 0 or search_end <= search_start + 0.35:
        return search_end

    i_start = max(0, int(search_start / hop_s))
    i_end = min(len(rms), int(search_end / hop_s))
    if i_end <= i_start + 5:
        return search_end

    window = rms[i_start:i_end]
    global_p90 = float(np.percentile(rms, 90)) if len(rms) > 0 else 0.0
    thresh = max(0.008, global_p90 * threshold_ratio)

    silence_frames = int(min_silence_s / hop_s)
    was_active = False
    last_active_idx = 0
    consecutive_silent = 0

    for idx, val in enumerate(window):
        if val > thresh:
            was_active = True
            last_active_idx = idx
            consecutive_silent = 0
        elif was_active:
            consecutive_silent += 1
            if consecutive_silent >= silence_frames:
                offset_time = (i_start + last_active_idx + 1) * hop_s + 0.15
                return min(search_end, max(search_start + 0.15, offset_time))

    if was_active:
        offset_time = (i_start + last_active_idx + 1) * hop_s + 0.15
        return min(search_end, max(search_start + 0.15, offset_time))

    return search_start


def refine_word_timestamps(
    transcription_result: Dict[str, Any],
    vocals_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    r"""
    Cleans and refines Whisper word timestamps:
    1. Strips [*] disfluency markers.
    2. Clamps phrase starts and ends to actual vocal energy onset/offset in vocals.wav.
    3. Redistributes squashed word timestamps (e.g. 0.02s \kf2) proportionally to Russian syllables.
    Returns a list of refined segments, each containing a list of refined words.
    """
    rms, hop_s = compute_vocal_rms_envelope(vocals_path)
    first_vocal_onset = find_first_vocal_onset(rms, hop_s)
    refined_segments = []

    raw_segments = transcription_result.get("segments", [])
    prev_seg_end = 0.0

    for seg in raw_segments:
        # If an instrumental intro is present, purge any hallucinated segments before actual vocal onset
        if first_vocal_onset is not None and float(seg.get("end", 0.0)) <= first_vocal_onset + 0.05:
            continue

        raw_words = seg.get("words", [])
        clean_words = []
        for w in raw_words:
            txt = clean_word_token(w.get("text", w.get("word", "")))
            if not txt:
                continue
            w_start = float(w.get("start", seg.get("start", prev_seg_end)))
            w_end = float(w.get("end", w_start + 0.25))
            if w_end < w_start:
                w_end = w_start + 0.15

            # Filter hallucinated words that finish before vocal onset
            if first_vocal_onset is not None and w_end <= first_vocal_onset:
                continue
            if first_vocal_onset is not None and w_start < first_vocal_onset:
                w_start = first_vocal_onset
                w_end = max(w_end, round(w_start + 0.15, 2))

            clean_words.append({
                "text": txt,
                "start": w_start,
                "end": w_end,
                "syllables": count_syllables(txt),
            })

        if not clean_words:
            continue

        # 1. Clamp stretched first and last word using vocal RMS onset and offset
        first_w = clean_words[0]
        if first_vocal_onset is not None and first_w["start"] < first_vocal_onset:
            first_w["start"] = first_vocal_onset

        if first_w["end"] - first_w["start"] > 0.75 or (first_w["start"] - prev_seg_end > 1.5):
            search_from = max(prev_seg_end, first_w["start"])
            real_onset = find_vocal_onset(rms, hop_s, search_from, first_w["end"], fallback=first_w["start"])
            if real_onset > first_w["start"] + 0.15:
                first_w["start"] = round(real_onset, 2)

        last_w = clean_words[-1]
        if last_w["end"] - last_w["start"] > 0.75:
            real_offset = find_vocal_offset(rms, hop_s, last_w["start"], last_w["end"])
            if real_offset < last_w["end"] - 0.2:
                last_w["end"] = round(real_offset, 2)

        # Check mid-segment words that stretched across pauses or trailing silence after punctuation
        for idx in range(len(clean_words) - 1):
            w_curr = clean_words[idx]
            w_next = clean_words[idx + 1]
            txt_curr = w_curr["text"].strip()
            dur_curr = w_curr["end"] - w_curr["start"]
            has_punct = bool(txt_curr and txt_curr[-1] in ",.!?;:—…-")

            # 1. Trim trailing silence from words ending with punctuation or exceeding natural syllable tempo
            if (has_punct and dur_curr > 0.40) or dur_curr > max(0.65, w_curr["syllables"] * 0.45):
                real_offset = find_vocal_offset(rms, hop_s, w_curr["start"], w_curr["end"], min_silence_s=0.15)
                if real_offset < w_curr["end"] - 0.18:
                    w_curr["end"] = round(real_offset, 2)

            # 2. Check next word's onset if stretched across pause
            dur_next = w_next["end"] - w_next["start"]
            if dur_next > 1.0 or (w_next["start"] - w_curr["end"] > 1.2):
                real_onset = find_vocal_onset(rms, hop_s, max(w_curr["end"], w_next["start"]), w_next["end"])
                if real_onset > w_next["start"] + 0.15:
                    w_next["start"] = round(real_onset, 2)

        # 2. Fix squashed words (< 0.12s duration) by redistributing within local phrase window
        n = len(clean_words)
        i = 0
        while i < n:
            dur = clean_words[i]["end"] - clean_words[i]["start"]
            if dur < 0.12:
                # Expand cluster to include adjacent squashed words and one neighbor with slack
                c_start = max(0, i - 1)
                c_end = i
                while c_end + 1 < n and (
                    (clean_words[c_end + 1]["end"] - clean_words[c_end + 1]["start"] < 0.14)
                    or (clean_words[c_end + 1]["start"] - clean_words[c_end]["end"] < 0.05)
                ):
                    c_end += 1

                win_start = clean_words[c_start]["start"]
                win_end = clean_words[c_end]["end"]
                cluster_count = c_end - c_start + 1
                min_needed = cluster_count * 0.18

                # Borrow slack before/after if window is too tight
                if win_end - win_start < min_needed:
                    prev_bound = clean_words[c_start - 1]["end"] if c_start > 0 else prev_seg_end
                    next_bound = (
                        clean_words[c_end + 1]["start"]
                        if c_end + 1 < n
                        else max(win_end + (min_needed - (win_end - win_start)), float(seg.get("end", win_end)))
                    )
                    deficit = min_needed - (win_end - win_start)
                    pull_back = min(deficit * 0.5, max(0.0, win_start - prev_bound))
                    push_fwd = min(deficit - pull_back, max(0.0, next_bound - win_end))
                    win_start -= pull_back
                    win_end += push_fwd

                total_syll = sum(clean_words[k]["syllables"] for k in range(c_start, c_end + 1))
                total_dur = max(0.10 * cluster_count, win_end - win_start)
                cursor = win_start
                for k in range(c_start, c_end + 1):
                    share = total_dur * (clean_words[k]["syllables"] / max(1, total_syll))
                    clean_words[k]["start"] = round(cursor, 2)
                    cursor += share
                    clean_words[k]["end"] = round(cursor, 2)
                i = c_end + 1
            else:
                i += 1

        # 3. Ensure monotonic non-overlapping timestamps
        for idx in range(1, n):
            if clean_words[idx]["start"] < clean_words[idx - 1]["end"]:
                mid = round((clean_words[idx]["start"] + clean_words[idx - 1]["end"]) / 2.0, 2)
                clean_words[idx - 1]["end"] = max(clean_words[idx - 1]["start"] + 0.08, mid)
                clean_words[idx]["start"] = clean_words[idx - 1]["end"]
            if clean_words[idx]["end"] <= clean_words[idx]["start"]:
                clean_words[idx]["end"] = round(clean_words[idx]["start"] + 0.15, 2)

        prev_seg_end = clean_words[-1]["end"]
        refined_segments.append({
            "start": clean_words[0]["start"],
            "end": clean_words[-1]["end"],
            "text": " ".join(w["text"] for w in clean_words),
            "words": clean_words,
        })

    return refined_segments


def align_russian_ctc_on_segments(
    segments: List[Dict[str, Any]],
    vocals_path: Path,
    device: str = "cpu"
) -> List[Dict[str, Any]]:
    """
    Refines word timestamps on Russian Cyrillic text using Wav2Vec2-Russian CTC model
    (jonatasgrosman/wav2vec2-large-xlsr-53-russian) + torchaudio forced alignment at 20ms frame resolution.
    Falls back cleanly if model is unavailable or a segment cannot be aligned.
    """
    if not vocals_path or not Path(vocals_path).exists() or not segments:
        return segments

    try:
        import torch
        import torchaudio
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        try:
            import transformers.utils.import_utils as tr_utils
            tr_utils.check_torch_load_is_safe = lambda: None
        except Exception:
            pass

        model_id = "jonatasgrosman/wav2vec2-large-xlsr-53-russian"
        print(f"[Karaoke] Running Cyrillic Wav2Vec2 CTC forced alignment ({model_id})...")
        processor = Wav2Vec2Processor.from_pretrained(model_id)
        ctc_model = Wav2Vec2ForCTC.from_pretrained(model_id).to(device)
        ctc_model.eval()

        waveform, sr = torchaudio.load(str(vocals_path))
        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)
        if sr != 16000:
            waveform = torchaudio.functional.resample(waveform, sr, 16000)
            sr = 16000

        vocab = processor.tokenizer.get_vocab()
        blank_id = processor.tokenizer.pad_token_id or 0

        for seg in segments:
            words = seg.get("words", [])
            if not words:
                continue

            seg_start = max(0.0, words[0]["start"] - 0.25)
            seg_end = words[-1]["end"] + 0.25
            s_sample = int(seg_start * sr)
            e_sample = min(waveform.shape[1], int(seg_end * sr))
            if e_sample - s_sample < 1600:  # < 0.1s
                continue

            chunk = waveform[:, s_sample:e_sample]
            with torch.no_grad():
                inputs = processor(chunk.squeeze(0).numpy(), sampling_rate=16000, return_tensors="pt")
                input_values = inputs.input_values.to(device)
                logits = ctc_model(input_values).logits
                log_probs = torch.nn.functional.log_softmax(logits, dim=-1).cpu()

            # Build Cyrillic character token sequence with word index mapping
            token_ids = []
            token_word_idx = []
            for w_idx, w in enumerate(words):
                clean_chars = re.sub(r"[^а-яё]", "", w["text"].lower().replace("ё", "е"))
                if not clean_chars:
                    continue
                for ch in clean_chars:
                    tid = vocab.get(ch)
                    if tid is not None:
                        token_ids.append(tid)
                        token_word_idx.append(w_idx)

            num_frames = log_probs.shape[1]
            if not token_ids or num_frames <= len(token_ids) * 2:
                continue

            targets = torch.tensor([token_ids], dtype=torch.int32)
            aligned_tokens, _ = torchaudio.functional.forced_align(
                log_probs, targets, blank=blank_id
            )
            aligned_seq = aligned_tokens[0].tolist()
            frame_dur = (e_sample - s_sample) / sr / num_frames

            # Map frames back to token positions
            word_frame_bounds: Dict[int, List[int]] = {}
            t_cursor = 0
            prev_tok = blank_id
            for f_idx, tok in enumerate(aligned_seq):
                if tok != blank_id:
                    if tok != prev_tok and t_cursor < len(token_ids) - 1 and aligned_seq[f_idx] == token_ids[min(len(token_ids)-1, t_cursor)]:
                        pass
                    w_i = token_word_idx[min(t_cursor, len(token_word_idx) - 1)]
                    if w_i not in word_frame_bounds:
                        word_frame_bounds[w_i] = [f_idx, f_idx]
                    else:
                        word_frame_bounds[w_i][1] = f_idx
                    # Advance t_cursor when next frame changes token
                    if f_idx + 1 < len(aligned_seq) and aligned_seq[f_idx + 1] != tok:
                        if t_cursor + 1 < len(token_ids):
                            t_cursor += 1
                prev_tok = tok

            # Apply refined bounds where valid
            for w_idx, w in enumerate(words):
                if w_idx in word_frame_bounds:
                    f_s, f_e = word_frame_bounds[w_idx]
                    new_s = round(seg_start + f_s * frame_dur, 2)
                    new_e = round(seg_start + (f_e + 1) * frame_dur, 2)
                    if new_e - new_s >= 0.08 and abs(new_s - w["start"]) < 1.5:
                        w["start"] = new_s
                        w["end"] = max(new_s + 0.12, new_e)

        del ctc_model
        if device == "mps":
            torch.mps.empty_cache()
        elif device == "cuda":
            torch.cuda.empty_cache()

    except Exception as e:
        print(f"[Karaoke] Note: Skipping Wav2Vec2 CTC pass ({e}), using RMS + syllable alignment.")

    return segments


def is_poetic_line_break(prev_word: Dict[str, Any], next_word: Dict[str, Any], current_line: List[Dict[str, Any]]) -> bool:
    """
    Determines if a natural poetic/verse line break occurs between prev_word and next_word.
    Handles Russian punctuation, pauses, and capitalized verse starts while preventing dangling prepositions.
    """
    prev_txt = prev_word["text"].strip()
    next_txt = next_word["text"].strip()
    prev_bare = re.sub(r"[^\wа-яёА-ЯЁ]", "", prev_txt).lower()

    # Never break right after a Russian preposition/conjunction/particle!
    if prev_bare in RUSSIAN_NO_DANGLE:
        return False

    gap = next_word["start"] - prev_word["end"]

    # Strong pause between phrases (> 0.65s)
    if gap > 0.65 and len(current_line) >= 2:
        return True

    # Sentence-ending punctuation (. ! ? ; …) ALWAYS ends a poetic line
    if prev_txt and prev_txt[-1] in ".!?;…":
        return True

    # Comma + Capitalized next word (Whisper marks poetic verse lines with uppercase after commas!)
    next_first_char = re.sub(r"^[^а-яёА-ЯЁa-zA-Z]+", "", next_txt)[:1]
    if prev_txt and prev_txt[-1] in ",—:" and next_first_char.isupper() and len(current_line) >= 2:
        return True

    # Capitalized next word after at least 3 words / 16 chars
    current_chars = sum(len(w["text"]) + 1 for w in current_line)
    if next_first_char.isupper() and len(current_line) >= 3 and current_chars >= 16:
        return True

    return False


def regroup_words_into_logical_lines(
    all_words: List[Dict[str, Any]],
    max_chars_per_line: int = 48,
    min_half_words: int = 4,
    min_half_chars: int = 15,
) -> List[List[Dict[str, Any]]]:
    """
    3-stage linguistic sentence and clause grouping for Russian karaoke:
    Stage 1: Group words into complete poetic clauses / sentences bounded by punctuation (.!?;…),
             genuine vocal pauses (>0.55s), or capitalized verse starts after commas.
    Stage 2: Keep clauses <= 48 chars & <= 9 words as a single line (preventing 2-3 word orphan tails
             like 'с качами,', 'у них,', 'и в рот.'). Only split genuinely long sentences near the middle
             at a comma or conjunction when BOTH halves have >= 4 words and >= 15 chars.
    Stage 3: Merge any remaining short orphan fragments (<= 3 words & < 14 chars) across small gaps.
    """
    if not all_words:
        return []

    # Acoustic refinement operates per segment. Adjacent segments can overlap
    # slightly at their boundary; reconcile these before reference alignment.
    # Never reorder words or repair reversed/repeated passages this way.
    for previous, current in zip(all_words, all_words[1:]):
        overlap = previous["end"] - current["start"]
        if (0 < overlap <= 0.25
                and previous["start"] < current["start"]
                and previous["end"] < current["end"]):
            boundary = round((previous["end"] + current["start"]) / 2, 3)
            if previous["start"] < boundary < current["end"]:
                previous["end"] = boundary
                current["start"] = boundary

    # Stage 1: Group into natural sentences / verse clauses
    clauses: List[List[Dict[str, Any]]] = []
    cur: List[Dict[str, Any]] = []
    for i, w in enumerate(all_words):
        cur.append(w)
        if i == len(all_words) - 1:
            break
        nxt = all_words[i + 1]
        txt = w["text"].strip()
        nxt_txt = nxt["text"].strip()
        bare = re.sub(r"[^\wа-яёА-ЯЁ]", "", txt).lower()
        gap = nxt["start"] - w["end"]
        nxt_first = re.sub(r"^[^а-яёА-ЯЁa-zA-Z]+", "", nxt_txt)[:1]
        cur_chars = sum(len(x["text"]) + 1 for x in cur) - 1

        # 1. Sentence-ending punctuation (. ! ? ; …) ALWAYS ends a clause
        if txt and txt[-1] in ".!?;…":
            clauses.append(cur)
            cur = []
            continue

        # Never break right after a Russian preposition/conjunction/particle
        if bare in RUSSIAN_NO_DANGLE:
            continue

        # 2. Genuine vocal pause between phrases (> 0.55s)
        if gap > 0.55 and len(cur) >= 2:
            clauses.append(cur)
            cur = []
            continue

        # 3. Comma/dash + Capitalized next word (new poetic verse line)
        if txt and txt[-1] in ",—:" and nxt_first.isupper():
            clauses.append(cur)
            cur = []
            continue

        # 4. Capitalized next word after a full clause (>= 18 chars & >= 3 words)
        if nxt_first.isupper() and cur_chars >= 18 and len(cur) >= 3:
            clauses.append(cur)
            cur = []
            continue

    if cur:
        clauses.append(cur)

    # Stage 2: Balanced split only for genuinely long clauses
    final_lines: List[List[Dict[str, Any]]] = []
    for cl in clauses:
        cl_chars = sum(len(x["text"]) + 1 for x in cl) - 1
        if cl_chars <= max_chars_per_line and len(cl) <= 9:
            final_lines.append(cl)
            continue

        best_idx = -1
        best_score = 999.0
        mid = len(cl) / 2.0
        for idx in range(2, len(cl) - 1):
            left = cl[:idx]
            right = cl[idx:]
            left_c = sum(len(x["text"]) + 1 for x in left) - 1
            right_c = sum(len(x["text"]) + 1 for x in right) - 1
            if len(left) < min_half_words or len(right) < min_half_words:
                continue
            if left_c < min_half_chars or right_c < min_half_chars:
                continue
            prev_w = cl[idx - 1]["text"].strip()
            prev_b = re.sub(r"[^\wа-яёА-ЯЁ]", "", prev_w).lower()
            if prev_b in RUSSIAN_NO_DANGLE:
                continue
            curr_b = re.sub(r"[^\wа-яёА-ЯЁ]", "", cl[idx]["text"]).lower()
            bonus = 0.0
            if prev_w and prev_w[-1] in ",—:":
                bonus -= 4.0
            if curr_b in {"и", "а", "но", "да", "или", "ведь", "что", "как", "где", "когда", "чтоб"}:
                bonus -= 3.0
            score = abs(idx - mid) + bonus
            if score < best_score:
                best_score = score
                best_idx = idx

        if best_idx != -1:
            final_lines.append(cl[:best_idx])
            final_lines.append(cl[best_idx:])
        else:
            final_lines.append(cl)

    # Stage 3: Post-pass to merge any remaining tiny orphan fragments (<= 3 words and < 14 chars)
    merged: List[List[Dict[str, Any]]] = []
    for line in final_lines:
        l_chars = sum(len(x["text"]) + 1 for x in line) - 1
        if merged:
            prev = merged[-1]
            prev_chars = sum(len(x["text"]) + 1 for x in prev) - 1
            gap = line[0]["start"] - prev[-1]["end"]
            prev_end_punct = prev[-1]["text"].strip()[-1:] in ".!?;…"
            if (
                len(line) <= 3
                and l_chars < 14
                and gap < 0.5
                and not prev_end_punct
                and (prev_chars + 1 + l_chars <= 54)
            ):
                prev.extend(line)
                continue
        merged.append(line)

    return merged


def split_into_karaoke_lines(
    segments: List[Dict[str, Any]],
    max_words_per_line: int = 9,
    max_chars_per_line: int = 48,
    reference_lyrics: Optional[str] = None,
    warnings_out: Optional[List[str]] = None,
    vocals_path: Optional[Path] = None,
    strict_repeats: bool = False,
) -> List[List[Dict[str, Any]]]:
    """
    Splits refined segments into natural poetic karaoke lines.
    - Respects Russian grammar (never leaves dangling prepositions like 'Жил в / горах').
    - Never creates 2-3 word orphan tail lines ('с качами,', 'у них,', 'и в рот.').
    - Respects verse boundaries (punctuation, pauses, capital letters).
    - If reference_lyrics is provided, aligns words to the user's reference lines.
    """
    all_words = []
    for seg in segments:
        seg_words = seg.get("words", [])
        for idx, w in enumerate(seg_words):
            w_copy = dict(w)
            w_copy["_seg_end"] = (idx == len(seg_words) - 1)
            all_words.append(w_copy)

    if not all_words:
        return []

    if reference_lyrics and reference_lyrics.strip():
        ref_lines = sanitize_reference_lyrics(reference_lyrics)
        if ref_lines:
            try:
                aligned = align_words_to_reference_lines(
                    all_words,
                    ref_lines,
                    vocals_path=vocals_path,
                    strict_repeats=strict_repeats,
                )
                if aligned:
                    return aligned
            except TimingAlignmentError as exc:
                message = f"{exc} Используется текст с таймингами распознавания."
                print(f"[Karaoke] {message}")
                if warnings_out is not None:
                    warnings_out.append(message)

    return regroup_words_into_logical_lines(
        all_words,
        max_chars_per_line=max_chars_per_line,
    )


class TimingAlignmentError(ValueError):
    """Text cannot safely be placed inside the available audio timestamps."""


def validate_karaoke_lines(lines: List[List[Dict[str, Any]]]) -> None:
    previous_end = 0.0
    for row, line in enumerate(lines, 1):
        for word in line:
            start, end = float(word["start"]), float(word["end"])
            if not math.isfinite(start + end) or start < 0 or end <= start:
                raise TimingAlignmentError(f"Строка {row}: неверный интервал слова «{word['text']}».")
            if start < previous_end - 0.011:
                raise TimingAlignmentError(
                    f"Строка {row}: тайминг «{word['text']}» возвращается назад "
                    f"({start:.2f} с после {previous_end:.2f} с). "
                    "Проверьте повторы текста и интервалы соседних строк."
                )
            previous_end = end


def _normalize_word(text: str) -> str:
    return re.sub(r"[^\wа-яёa-z]", "", text.lower().replace("ё", "е"))


def _word_similarity(w1: str, w2: str) -> float:
    """Computes phonetic and morphological similarity between Russian/English word tokens."""
    if w1 == w2:
        return 1.0
    if not w1 or not w2:
        return 0.0
    c1 = re.sub(r"[^\wа-яёa-z]", "", w1.lower()).replace("ё", "е")
    c2 = re.sub(r"[^\wа-яёa-z]", "", w2.lower()).replace("ё", "е")
    if c1 == c2:
        return 1.0
    # Russian demonstratives / pronouns case variations (этот / эта / это / эти / этой / этом / этого...)
    demonstratives = {"этот", "эта", "это", "эти", "этой", "этом", "этому", "этого", "этим", "этих"}
    if c1 in demonstratives and c2 in demonstratives:
        return 0.92
    # Russian verb endings: -ться / -тся
    if (c1.endswith("ться") and c2.endswith("тся") and c1[:-4] == c2[:-3]) or \
       (c1.endswith("тся") and c2.endswith("ться") and c1[:-3] == c2[:-4]):
        return 0.95
    # Russian acoustic confusion normalization: voiceless/voiced fricatives (ф <-> х, etc.)
    p1 = c1.replace("ф", "х")
    p2 = c2.replace("ф", "х")
    if p1 == p2:
        return 0.94
    # Russian adjective/participle endings: -ий/-ый/-ой/-ие/-ые/-их
    min_len = min(len(p1), len(p2))
    if min_len >= 4:
        p = 0
        while p < min_len and p1[p] == p2[p]:
            p += 1
        if p >= min_len - 1 and abs(len(p1) - len(p2)) <= 2:
            return 0.88
        if p >= 4 and p >= max(len(p1), len(p2)) - 2:
            return 0.82
    return difflib.SequenceMatcher(None, p1, p2).ratio()


def _sequence_opcodes(
    reference: List[str],
    recognized: List[str],
    recognized_words: Optional[List[Dict[str, Any]]] = None,
):
    """Minimum-edit monotonic alignment with fuzzy Russian morphology & stop-word jump protection."""
    n, m = len(reference), len(recognized)
    trace = np.zeros((n + 1, m + 1), dtype=np.uint8)
    trace[1:, 0] = 1
    trace[0, 1:] = 2
    del_costs = [3.0] * (m + 1)
    if recognized_words and len(recognized_words) == m:
        for j in range(1, m):
            gap = float(recognized_words[j].get("start", 0.0)) - float(recognized_words[j - 1].get("end", 0.0))
            if gap >= 1.2:
                del_costs[j] = 2.85
            elif gap < 0.15:
                del_costs[j] = 3.05

    previous = [2.0 * j for j in range(m + 1)]
    for i in range(1, n + 1):
        ref_w = reference[i - 1]
        is_short_ref = len(ref_w) <= 2
        current = [3.0 * i] + [0.0] * m
        for j in range(1, m + 1):
            rec_w = recognized[j - 1]
            sim = _word_similarity(ref_w, rec_w)
            is_exact = (sim >= 0.99)
            is_fuzzy = (sim >= 0.74)

            has_left_context = (i > 1 and j > 1 and _word_similarity(reference[i - 2], recognized[j - 2]) >= 0.74)
            has_right_context = (i < n and j < m and _word_similarity(reference[i], recognized[j]) >= 0.74)
            has_context = (has_left_context or has_right_context)

            # Stray words floating after an instrumental gap (> 4.5s) without context agreement
            is_isolated_after_large_gap = False
            if recognized_words and j > 1:
                gap = float(recognized_words[j - 1].get("start", 0.0)) - float(recognized_words[j - 2].get("end", 0.0))
                if gap >= 4.5 and not has_context:
                    is_isolated_after_large_gap = True

            # Short words (<= 2 chars) require adjacent context agreement to avoid jumping across instrumental gaps
            if is_short_ref and is_fuzzy:
                if not has_context:
                    match_cost = 2.2
                else:
                    match_cost = 0.0 if is_exact else 0.35
            elif is_isolated_after_large_gap:
                match_cost = 2.4
            elif is_exact:
                match_cost = 0.0
            elif is_fuzzy:
                match_cost = 0.35
            else:
                match_cost = 5.2

            pos_tie = 1e-4 * i if is_fuzzy else 0.0
            costs = (
                previous[j - 1] + match_cost + pos_tie,
                previous[j] + del_costs[j],
                current[j - 1] + 2.0,
            )
            direction = min(range(3), key=costs.__getitem__)
            current[j] = costs[direction]
            trace[i, j] = direction
        previous = current

    actions = []
    i, j = n, m
    while i or j:
        direction = trace[i, j]
        if direction == 0:
            sim = _word_similarity(reference[i - 1], recognized[j - 1])
            actions.append("equal" if sim >= 0.74 else "replace")
            i -= 1
            j -= 1
        elif direction == 1:
            actions.append("delete")
            i -= 1
        else:
            actions.append("insert")
            j -= 1

    actions.reverse()

    # Group consecutive actions of the exact same kind without merging distinct operations
    i = j = 0
    group = None
    for action in actions:
        if group and group[0] != action:
            tag, a, b = group
            yield (tag, a, i, b, j)
            group = None
        if group is None:
            group = (action, i, j)
        i += (action != "insert")
        j += (action != "delete")
    if group:
        tag, a, b = group
        yield (tag, a, i, b, j)


def _distribute_words(tokens: List[str], start: float, end: float) -> List[Dict[str, Any]]:
    if end <= start:
        raise TimingAlignmentError("Для добавленных слов нет свободного временного интервала.")
    n = len(tokens)
    if n == 0:
        return []
    syllables = [count_syllables(t) for t in tokens]
    total_syll = max(1, sum(syllables))
    dur = end - start

    # Compute requested breath pauses based on punctuation
    req_pauses = [0.0] * n
    for k in range(n - 1):
        txt = tokens[k].strip()
        if not txt:
            continue
        last_char = txt[-1]
        if last_char in ".!?;…":
            req_pauses[k] = 0.25
        elif last_char in ",—:":
            req_pauses[k] = 0.16
        else:
            req_pauses[k] = 0.03  # small inter-word acoustic boundary gap

    min_sing_time = total_syll * 0.08
    tot_req_pause = sum(req_pauses)

    if dur <= min_sing_time:
        pauses = [0.0] * n
        sing_dur = dur
    else:
        avail_for_pauses = max(0.0, dur - min_sing_time)
        scale_p = min(1.0, avail_for_pauses / max(0.001, tot_req_pause)) if tot_req_pause > 0 else 0.0
        pauses = [round(p * scale_p, 3) for p in req_pauses]
        sing_dur = dur - sum(pauses)

    cursor = start
    result = []
    for k, (token, count) in enumerate(zip(tokens, syllables)):
        w_dur = sing_dur * (count / total_syll)
        w_start = round(cursor, 3)
        w_end = round(w_start + w_dur, 3)
        result.append({"text": token, "start": w_start, "end": w_end, "syllables": count})
        cursor = w_end + pauses[k]

    result[-1]["end"] = round(end, 3)
    return result


def align_words_to_reference_lines(
    recognized_words: List[Dict[str, Any]],
    ref_lines: List[str],
    vocals_path: Optional[Path] = None,
    strict_repeats: bool = False,
) -> List[List[Dict[str, Any]]]:
    """
    Maps a user's reference lyric lines to the recognized word timestamps using fuzzy sequence alignment.
    """
    ref_lines = sanitize_reference_lyrics(ref_lines)
    ref_tokenized: List[List[str]] = []
    flat_ref: List[Tuple[int, str, str]] = []  # (line_idx, raw_word, normalized_word)

    for l_idx, line_str in enumerate(ref_lines):
        raw_tokens = [t for t in line_str.split() if t.strip()]
        if not raw_tokens:
            continue
        # Merge standalone punctuation tokens (e.g. "—", "-", "...") to the preceding word
        tokens: List[str] = []
        for t in raw_tokens:
            if re.sub(r"[^\wа-яёa-z]", "", t.lower()):
                tokens.append(t)
            elif tokens:
                tokens[-1] += f" {t}"
            else:
                tokens.append(t)
        if not tokens:
            continue
        ref_tokenized.append(tokens)
        actual_l_idx = len(ref_tokenized) - 1
        for t in tokens:
            norm = _normalize_word(t)
            flat_ref.append((actual_l_idx, t, norm))

    if not flat_ref or not recognized_words:
        return []

    rms, hop_s = compute_vocal_rms_envelope(vocals_path)

    # Check if Whisper split any single reference word into 2 consecutive adjacent tokens
    # e.g. "три" + "пуфи" -> "трипуфи" matching "стрипухе"
    ref_norm_set = set(item[2] for item in flat_ref)
    processed_rec_words: List[Dict[str, Any]] = []
    skip_next = False
    for k in range(len(recognized_words)):
        if skip_next:
            skip_next = False
            continue
        curr_w = recognized_words[k]
        if k + 1 < len(recognized_words):
            next_w = recognized_words[k + 1]
            gap = float(next_w.get("start", 0.0)) - float(curr_w.get("end", 0.0))
            if gap <= 0.20:
                combo_norm = _normalize_word(curr_w["text"] + next_w["text"])
                best_sim = max((_word_similarity(rn, combo_norm) for rn in ref_norm_set), default=0.0)
                indiv_sim = max(
                    max((_word_similarity(rn, _normalize_word(curr_w["text"])) for rn in ref_norm_set), default=0.0),
                    max((_word_similarity(rn, _normalize_word(next_w["text"])) for rn in ref_norm_set), default=0.0),
                )
                if best_sim >= 0.76 and best_sim > indiv_sim + 0.15:
                    processed_rec_words.append({
                        "text": curr_w["text"] + next_w["text"],
                        "start": curr_w["start"],
                        "end": next_w["end"],
                        "syllables": count_syllables(curr_w["text"] + next_w["text"]),
                    })
                    skip_next = True
                    continue
        processed_rec_words.append(curr_w)

    recognized_words = processed_rec_words
    rec_norms = [_normalize_word(w["text"]) for w in recognized_words]
    ref_norms = [item[2] for item in flat_ref]

    ref_to_time: List[Optional[Tuple[float, float]]] = [None] * len(flat_ref)

    for tag, i1, i2, j1, j2 in _sequence_opcodes(ref_norms, rec_norms, recognized_words):
        if tag == "equal":
            for offset in range(i2 - i1):
                rw = recognized_words[j1 + offset]
                s_val, e_val = rw["start"], rw["end"]
                ref_w = flat_ref[i1 + offset][1].strip()
                if rms is not None and len(rms) > 0:
                    dur_w = e_val - s_val
                    has_punct = bool(ref_w and ref_w[-1] in ",.!?;:—…-")
                    if (has_punct and dur_w > 0.45) or dur_w > max(0.65, count_syllables(ref_w) * 0.45):
                        real_off = find_vocal_offset(rms, hop_s, s_val, e_val, min_silence_s=0.15)
                        if real_off < e_val - 0.18:
                            e_val = round(real_off, 2)
                ref_to_time[i1 + offset] = (s_val, e_val)
        elif tag == "replace" and (j2 > j1) and (i2 > i1):
            win_start = recognized_words[j1]["start"]
            win_end = recognized_words[j2 - 1]["end"]
            sylls = [count_syllables(flat_ref[k][1]) for k in range(i1, i2)]
            tot_syll = max(1, sum(sylls))
            dur = win_end - win_start
            if dur < 0.06 * (i2 - i1):
                if strict_repeats:
                    raise TimingAlignmentError("В готовом тексте есть лишние повторы или слишком много слов для распознанного интервала.")
                dur = max(dur, 0.06 * (i2 - i1))
                win_end = max(win_end, win_start + dur)
            # Bound replacement duration to prevent smearing across omitted audio sections
            max_natural_dur = tot_syll * 0.85
            if dur > max_natural_dur:
                win_end = win_start + max_natural_dur
                dur = win_end - win_start
            cur = win_start
            for idx_k, k in enumerate(range(i1, i2)):
                step = dur * (sylls[idx_k] / tot_syll)
                ref_to_time[k] = (round(cur, 2), round(cur + step, 2))
                cur += step

    # Density & Sanity Guard: reject spurious short anchors (<= 2 words) that force impossible compression (< 0.12s/word)
    k = 0
    n_ref = len(flat_ref)
    while k < n_ref:
        if ref_to_time[k] is not None:
            anchor_start = k
            while k < n_ref and ref_to_time[k] is not None:
                k += 1
            anchor_end = k
            anchor_len = anchor_end - anchor_start
            if anchor_len <= 2:
                s_first, _ = ref_to_time[anchor_start]
                _, e_last = ref_to_time[anchor_end - 1]
                # Left check
                prev_k = anchor_start - 1
                while prev_k >= 0 and ref_to_time[prev_k] is None:
                    prev_k -= 1
                count_l = anchor_start - 1 - prev_k
                t_prev = ref_to_time[prev_k][1] if prev_k >= 0 else 0.0
                dur_l = max(0.0, s_first - t_prev)
                if count_l >= 3 and dur_l < count_l * 0.12:
                    for cl_k in range(anchor_start, anchor_end):
                        ref_to_time[cl_k] = None
                    continue

                # Right check
                next_k = anchor_end
                while next_k < n_ref and ref_to_time[next_k] is None:
                    next_k += 1
                count_r = next_k - anchor_end
                if next_k < n_ref:
                    t_next = ref_to_time[next_k][0]
                    dur_r = max(0.0, t_next - e_last)
                    if count_r >= 3 and dur_r < count_r * 0.12:
                        for cl_k in range(anchor_start, anchor_end):
                            ref_to_time[cl_k] = None
                        continue
        else:
            k += 1

    # Interpolate any remaining None entries (insertions)
    total_rec_start = recognized_words[0]["start"]
    total_rec_end = recognized_words[-1]["end"]
    idx = 0
    while idx < n_ref:
        if ref_to_time[idx] is None:
            end_none = idx
            while end_none + 1 < n_ref and ref_to_time[end_none + 1] is None:
                end_none += 1
            count = end_none - idx + 1
            has_left = idx > 0 and ref_to_time[idx - 1] is not None
            has_right = end_none + 1 < n_ref and ref_to_time[end_none + 1] is not None

            if has_left:
                left_s, left_e = ref_to_time[idx - 1]
            else:
                first_onset = find_first_vocal_onset(rms, hop_s)
                first_valid_anchor = next((ref_to_time[k][0] for k in range(n_ref) if ref_to_time[k] is not None), total_rec_start)
                anchor_base = ref_to_time[end_none + 1][0] if has_right else first_valid_anchor
                sylls_needed = [count_syllables(flat_ref[k][1]) for k in range(idx, end_none + 1)]
                dur_needed = max(count * 0.40, min(count * 0.85, sum(sylls_needed) * 0.38))
                target_start = max(0.0, anchor_base - dur_needed)
                if first_onset is not None:
                    # Never start earlier than actual first vocal onset in audio.
                    # Bound natural duration so it clusters near anchor_base, preserving instrumental intro.
                    left_s = left_e = max(first_onset, target_start)
                else:
                    left_s = left_e = target_start

            if has_right:
                r_start = end_none + 1
                if count >= 3:
                    r_line = flat_ref[r_start][0]
                    stretch_k = None
                    for k_r in range(r_start, min(n_ref, r_start + 6)):
                        if flat_ref[k_r][0] != r_line or ref_to_time[k_r] is None:
                            break
                        ws_r, we_r = ref_to_time[k_r]
                        sy_r = count_syllables(flat_ref[k_r][1])
                        if we_r - ws_r > max(1.4, sy_r * 0.85):
                            stretch_k = k_r
                    if stretch_k is not None:
                        _, anchor_end = ref_to_time[stretch_k]
                        pref_sylls = [count_syllables(flat_ref[k_r][1]) for k_r in range(r_start, stretch_k + 1)]
                        pref_dur = sum(pref_sylls) * 0.25
                        new_r_start = max(left_e + 0.5, anchor_end - pref_dur)
                        if new_r_start > ref_to_time[r_start][0] + 1.0:
                            cur_r = new_r_start
                            for idx_r, k_r in enumerate(range(r_start, stretch_k + 1)):
                                step_r = (anchor_end - new_r_start) * (pref_sylls[idx_r] / max(1, sum(pref_sylls)))
                                ref_to_time[k_r] = (round(cur_r, 2), round(cur_r + step_r, 2))
                                cur_r += step_r
                right_s, right_e = ref_to_time[end_none + 1]
            else:
                audio_end = len(rms) * hop_s if rms is not None and len(rms) > 0 else total_rec_end
                sylls_trailing = [count_syllables(flat_ref[k][1]) for k in range(idx, end_none + 1)]
                needed_tail = sum(sylls_trailing) * 0.45
                right_s = right_e = min(audio_end, max(total_rec_end, left_e + needed_tail))

            gap = right_s - left_e
            min_needed = 0.08 * count

            if gap < min_needed:
                needed = min_needed - max(0.0, gap)
                borrow_l = min((left_e - left_s) * 0.45, needed * 0.5) if has_left else 0.0
                borrow_r = min((right_e - right_s) * 0.45, needed * 0.5) if has_right else 0.0
                if not has_left:
                    borrow_r = min((right_e - right_s) * 0.45, needed)
                if not has_right:
                    borrow_l = min((left_e - left_s) * 0.45, needed)

                if has_left and borrow_l > 0:
                    left_e -= borrow_l
                    ref_to_time[idx - 1] = (round(left_s, 2), round(left_e, 2))
                if has_right and borrow_r > 0:
                    right_s += borrow_r
                    ref_to_time[end_none + 1] = (round(right_s, 2), round(right_e, 2))

            dur = right_s - left_e
            sylls = [count_syllables(flat_ref[k][1]) for k in range(idx, end_none + 1)]
            tot_s = max(1, sum(sylls))

            curr_l = flat_ref[idx][0]
            right_l = flat_ref[end_none + 1][0] if has_right else None
            left_l = flat_ref[idx - 1][0] if has_left else None

            # Guard against stretching words across instrumental pauses
            max_natural_dur = max(0.35, tot_s * 0.55)
            if dur > max_natural_dur:
                # If vocals envelope is available, detect actual vocal activity within the gap
                if rms is not None and len(rms) > 0 and dur > 1.8:
                    sub_onset = find_vocal_onset(rms, hop_s, left_e, right_s, fallback=left_e)
                    sub_offset = find_vocal_offset(rms, hop_s, sub_onset, right_s, min_silence_s=0.25)
                    if sub_offset > sub_onset + 0.25:
                        left_e = sub_onset
                        right_s = max(sub_offset, min(right_s, sub_onset + tot_s * 0.45))
                        dur = right_s - left_e

                if dur > max_natural_dur:
                    # Anchor words according to punctuation and phrase boundaries
                    last_missing_txt = flat_ref[end_none][1].strip()
                    prev_txt = flat_ref[idx - 1][1].strip() if has_left else ""
                    last_has_punct = bool(last_missing_txt and last_missing_txt[-1] in ",.!?;:—…-")
                    prev_has_punct = bool(prev_txt and prev_txt[-1] in ",.!?;:—…-")

                    if has_left and not has_right:
                        right_s = left_e + max_natural_dur
                    elif has_right and not has_left:
                        first_onset = find_first_vocal_onset(rms, hop_s)
                        min_start = first_onset if first_onset is not None else total_rec_start
                        left_e = max(min_start, right_s - max_natural_dur)
                    elif last_has_punct and not prev_has_punct:
                        # Missing phrase ends with punctuation: anchor to left, pause before right
                        right_s = left_e + max_natural_dur
                    elif prev_has_punct and not last_has_punct:
                        # Pause occurred after prev word: anchor backwards from right
                        left_e = max(left_e + 0.1, right_s - max_natural_dur)
                    elif has_right and has_left and right_l == curr_l and left_l != curr_l:
                        # Words belong to the right line: anchor backwards from right
                        prefix_dur = min(max_natural_dur, tot_s * 0.45)
                        left_e = max(left_e + 0.1, right_s - prefix_dur)
                    elif has_right and has_left and left_l == curr_l and right_l != curr_l:
                        # Missing phrase finishes current line: anchor to left, reserve pause before next line
                        right_s = left_e + max_natural_dur
                    else:
                        right_s = min(right_s, left_e + max_natural_dur)
                    dur = right_s - left_e

            if dur < (0.08 if strict_repeats else 0.05) * count:
                if strict_repeats:
                    raise TimingAlignmentError(
                        "Не удалось привязать готовый текст к вокалу: лишние повторы или пропущенные слова. "
                        "Нужны тайминги по аудио; сдвигать следующие строки автоматически нельзя."
                    )
                dur = max(0.06 * count, dur)
                right_s = max(right_s, left_e + dur)

            sub_tokens = [flat_ref[k][1] for k in range(idx, end_none + 1)]
            distributed = _distribute_words(sub_tokens, left_e, right_s)
            for offset_k, dw in enumerate(distributed):
                ref_to_time[idx + offset_k] = (dw["start"], dw["end"])
            idx = end_none + 1
        else:
            idx += 1

    # Enforce strict forward monotonicity and positive non-zero word durations
    first_vocal_onset = find_first_vocal_onset(rms, hop_s)
    prev_end = first_vocal_onset if first_vocal_onset is not None else 0.0
    for k in range(len(ref_to_time)):
        if ref_to_time[k] is None:
            continue
        s, e = ref_to_time[k]
        if s < prev_end:
            s = prev_end
        if e <= s:
            e = round(s + 0.08, 2)
        ref_to_time[k] = (round(s, 2), round(e, 2))
        prev_end = e

    # Group back into lines
    grouped_lines: List[List[Dict[str, Any]]] = [[] for _ in range(len(ref_tokenized))]
    for k, (l_idx, raw_word, _) in enumerate(flat_ref):
        s_t, e_t = ref_to_time[k]
        grouped_lines[l_idx].append({
            "text": raw_word,
            "start": s_t,
            "end": e_t,
            "syllables": count_syllables(raw_word),
        })

    # Outlier Word Guard: if the first or last word of a line is detached by >2.0s
    # from the main phrase cluster, pull it to the phrase cluster so stray short words ("Ты", "Я")
    # don't get stranded across long instrumental breaks.
    for line in grouped_lines:
        if len(line) >= 2:
            gap0 = line[1]["start"] - line[0]["end"]
            if gap0 > 2.0:
                word_dur = min(0.6, max(0.15, line[0]["end"] - line[0]["start"]))
                new_start = round(max(line[0]["start"], line[1]["start"] - word_dur - 0.08), 2)
                line[0]["start"] = new_start
                line[0]["end"] = round(new_start + word_dur, 2)
        if len(line) >= 3:
            gap1 = line[-1]["start"] - line[-2]["end"]
            if gap1 > 2.0:
                word_dur = min(0.6, max(0.15, line[-1]["end"] - line[-1]["start"]))
                new_start = round(line[-2]["end"] + 0.08, 2)
                line[-1]["start"] = new_start
                line[-1]["end"] = round(new_start + word_dur, 2)

    result = [line for line in grouped_lines if line]
    validate_karaoke_lines(result)
    return result


def format_editor_timestamp(seconds: float) -> str:
    """Formats seconds as MM:SS.cc for the Lyrics Editor."""
    seconds = max(0.0, float(seconds))
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins:02d}:{secs:05.2f}"


def parse_editor_timestamp(ts_str: str) -> float:
    """Parses MM:SS.cc or H:MM:SS.cc or SS.cc into float seconds."""
    clean = ts_str.strip().replace(",", ".")
    parts = [p.strip() for p in clean.split(":") if p.strip()]
    if len(parts) == 3:
        return round(int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2]), 3)
    elif len(parts) == 2:
        return round(int(parts[0]) * 60 + float(parts[1]), 3)
    return round(float(parts[0]), 3)


def lines_to_editor_text(lines: List[List[Dict[str, Any]]]) -> str:
    """
    Converts structured karaoke lines into an intuitive, editable text format:
    [00:17.60 -> 00:21.20] Я был хач широкоплечий,
    """
    out = []
    for line in lines:
        if not line:
            continue
        start_str = format_editor_timestamp(line[0]["start"])
        end_str = format_editor_timestamp(line[-1]["end"])
        text_str = " ".join(w["text"] for w in line)
        out.append(f"[{start_str} -> {end_str}] {text_str}")
    return "\n".join(out)


def align_words_in_line_window(
    new_words_str: List[str],
    line_start: float,
    line_end: float,
    cached_words: List[Dict[str, Any]],
    original_line: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Preserve acoustic anchors when possible; never expand the editor's window."""
    if not new_words_str:
        return []
    if line_end <= line_start:
        raise TimingAlignmentError("Конец строки должен быть позже её начала.")
    # The explicit original row wins over neighboring copies of the same chorus.
    window_words = original_line if original_line is not None else [
        w for w in cached_words if w["end"] > line_start and w["start"] < line_end
    ]
    if not window_words:
        return _distribute_words(new_words_str, line_start, line_end)
    old_norms = [_normalize_word(w["text"]) for w in window_words]
    new_norms = [_normalize_word(w) for w in new_words_str]
    assigned = [None] * len(new_words_str)
    for tag, i1, i2, j1, j2 in _sequence_opcodes(new_norms, old_norms):
        if tag == "equal":
            for offset in range(i2 - i1):
                w = window_words[j1 + offset]
                assigned[i1 + offset] = (w["start"], w["end"])
        elif tag == "replace" and j2 > j1:
            start, end = window_words[j1]["start"], window_words[j2 - 1]["end"]
            if end <= start:
                return _distribute_words(new_words_str, line_start, line_end)
            for k, w in enumerate(_distribute_words(new_words_str[i1:i2], start, end), i1):
                assigned[k] = (w["start"], w["end"])
    i = 0
    while i < len(assigned):
        if assigned[i] is not None:
            i += 1
            continue
        j = i + 1
        while j < len(assigned) and assigned[j] is None:
            j += 1
        start = assigned[i - 1][1] if i else line_start
        end = assigned[j][0] if j < len(assigned) else line_end
        if end <= start:
            return _distribute_words(new_words_str, line_start, line_end)
        for k, w in enumerate(_distribute_words(new_words_str[i:j], start, end), i):
            assigned[k] = (w["start"], w["end"])
        i = j
    origin_start, origin_end = assigned[0][0], assigned[-1][1]
    if origin_end <= origin_start or any(
        end <= start or (k and start < assigned[k - 1][1] - 0.011)
        for k, (start, end) in enumerate(assigned)
    ):
        return _distribute_words(new_words_str, line_start, line_end)
    # Shift if user moved line_start after the acoustic onset
    if origin_start < line_start:
        delta = line_start - origin_start
        assigned = [(s + delta, e + delta) for s, e in assigned]
        origin_start, origin_end = assigned[0][0], assigned[-1][1]

    # Only compress if words overshoot line_end; NEVER stretch to fill trailing silence
    if origin_end > line_end:
        avail = max(0.08 * len(assigned), line_end - origin_start)
        span = origin_end - origin_start
        scale = avail / span if span > 0 else 1.0
        assigned = [
            (
                round(origin_start + (s - origin_start) * scale, 3),
                round(origin_start + (e - origin_start) * scale, 3),
            )
            for s, e in assigned
        ]

    return [{
        "text": token,
        "start": round(start, 3),
        "end": round(end, 3),
        "syllables": count_syllables(token),
    } for token, (start, end) in zip(new_words_str, assigned)]


def editor_text_to_lines(
    editor_text: str,
    original_lines: Optional[List[List[Dict[str, Any]]]] = None,
    vocals_path: Optional[Path] = None,
) -> List[List[Dict[str, Any]]]:
    """
    Parses the user's edited text from the Lyrics Editor back into word-timed karaoke lines.
    Supports:
    - Timestamped lines: `[00:17.60 -> 00:21.20] Я был хач широкоплечий,`
    - Full timestamps: `[00:00:01->00:01:00]` or with any arrows/dashes
    - Plain lines without timestamps (e.g. user pressed Enter to split a line or pasted raw text)
    - Duplicate/overlapping timestamps on split lines (auto-partitioned by acoustic words)
    - Text modifications and recognition error fixes
    """
    cached_words: List[Dict[str, Any]] = []
    if original_lines:
        for line in original_lines:
            cached_words.extend(line)

    raw_rows = [r.strip() for r in editor_text.splitlines() if r.strip()]
    if not raw_rows:
        return []

    pattern = re.compile(r"^\[\s*([0-9:.,]+)\s*(?:-->|->|—|–|-)\s*([0-9:.,]+)\s*\]\s*(.*)$")
    parsed_rows: List[Dict[str, Any]] = []
    any_timestamps = False

    for r in raw_rows:
        m = pattern.match(r)
        if m:
            s_time = parse_editor_timestamp(m.group(1))
            e_time = parse_editor_timestamp(m.group(2))
            txt = m.group(3).strip()
            if e_time <= s_time:
                raise TimingAlignmentError(f"Конец строки «{txt}» должен быть позже начала ({e_time:.2f} <= {s_time:.2f}).")
            if parsed_rows and parsed_rows[-1]["start"] is not None:
                prev_s = parsed_rows[-1]["start"]
                prev_e = parsed_rows[-1]["end"]
                if s_time < prev_s:
                    raise TimingAlignmentError(
                        f"Тайминг строки «{txt}» ({s_time:.2f} с) идет раньше начала предыдущей строки ({prev_s:.2f} с)."
                    )
                if s_time < prev_e and not cached_words:
                    raise TimingAlignmentError(
                        f"Тайминг строки «{txt}» ({s_time:.2f} с) накладывается на предыдущую строку ({prev_e:.2f} с)."
                    )
            parsed_rows.append({"start": s_time, "end": e_time, "text": txt, "has_ts": True})
            any_timestamps = True
        else:
            parsed_rows.append({"start": None, "end": None, "text": r, "has_ts": False})

    # If completely raw lyrics without any [MM:SS -> MM:SS], align to cached_words
    if not any_timestamps and cached_words:
        return align_words_to_reference_lines(
            cached_words,
            [r["text"] for r in parsed_rows],
            vocals_path=vocals_path,
            strict_repeats=False,
        )

    # Resolve spans for rows with missing timestamps or duplicate/overlapping timestamps (from Enter splits)
    n_rows = len(parsed_rows)
    i = 0
    while i < n_rows:
        row = parsed_rows[i]
        prev_end = parsed_rows[i - 1]["end"] if i > 0 and parsed_rows[i - 1]["end"] is not None else None
        needs_span = (not row["has_ts"]) or (prev_end is not None and row["start"] is not None and row["start"] < prev_end - 0.01)

        if not needs_span:
            i += 1
            continue

        # Determine span indices
        span_start_idx = i - 1 if (i > 0 and parsed_rows[i - 1]["start"] is not None) else i
        span_end_idx = i
        while span_end_idx + 1 < n_rows:
            nxt = parsed_rows[span_end_idx + 1]
            if not nxt["has_ts"]:
                span_end_idx += 1
            elif parsed_rows[span_start_idx]["end"] is not None and nxt["start"] is not None and nxt["start"] < parsed_rows[span_start_idx]["end"]:
                span_end_idx += 1
            else:
                break

        # Bounding window for this span
        win_start = parsed_rows[span_start_idx]["start"]
        if win_start is None:
            win_start = parsed_rows[span_start_idx - 1]["end"] if span_start_idx > 0 else (cached_words[0]["start"] if cached_words else 0.0)

        nxt_start = parsed_rows[span_end_idx + 1]["start"] if span_end_idx + 1 < n_rows else None
        orig_end = parsed_rows[span_start_idx]["end"]
        if orig_end is not None and (nxt_start is None or orig_end <= nxt_start):
            win_end = orig_end
        elif nxt_start is not None:
            win_end = nxt_start
        else:
            win_end = win_start + 3.0 * (span_end_idx - span_start_idx + 1)

        span_indices = list(range(span_start_idx, span_end_idx + 1))
        span_texts = [parsed_rows[k]["text"] for k in span_indices]

        # Try to align span words using cached_words within win_start..win_end
        span_cached = [w for w in cached_words if w["end"] >= win_start - 0.15 and w["start"] <= win_end + 0.15] if cached_words else []
        aligned_span = None
        if span_cached:
            try:
                aligned_span = align_words_to_reference_lines(
                    span_cached,
                    span_texts,
                    vocals_path=vocals_path,
                    strict_repeats=False,
                )
            except Exception:
                aligned_span = None

        if aligned_span and len(aligned_span) == len(span_indices):
            for idx_k, k in enumerate(span_indices):
                line_words = aligned_span[idx_k]
                parsed_rows[k]["start"] = line_words[0]["start"]
                parsed_rows[k]["end"] = line_words[-1]["end"]
                parsed_rows[k]["_pre_aligned"] = line_words
                parsed_rows[k]["has_ts"] = True
        else:
            # Fallback: proportional allocation by syllables within win_start..win_end
            sylls = [sum(count_syllables(w) for w in parsed_rows[k]["text"].split()) for k in span_indices]
            tot_s = max(1, sum(sylls))
            dur = max(0.1 * len(span_indices), win_end - win_start)
            cur = win_start
            for idx_k, k in enumerate(span_indices):
                step = dur * (sylls[idx_k] / tot_s)
                parsed_rows[k]["start"] = round(cur, 2)
                parsed_rows[k]["end"] = round(cur + step, 2)
                parsed_rows[k]["has_ts"] = True
                cur += step

        i = span_end_idx + 1

    # Align words inside each line
    final_lines: List[List[Dict[str, Any]]] = []
    for row_index, row in enumerate(parsed_rows):
        if "_pre_aligned" in row and row["_pre_aligned"]:
            final_lines.append(row["_pre_aligned"])
            continue

        words_str = [w.strip() for w in row["text"].split() if w.strip()]
        if not words_str:
            continue
        original_line = None
        if original_lines and len(original_lines) == len(parsed_rows):
            candidate = original_lines[row_index]
            if [_normalize_word(w["text"]) for w in candidate] == [_normalize_word(w) for w in words_str]:
                original_line = candidate
        aligned_line = align_words_in_line_window(
            words_str,
            row["start"],
            row["end"],
            cached_words,
            original_line=original_line,
        )
        if aligned_line:
            final_lines.append(aligned_line)

    validate_karaoke_lines(final_lines)
    return final_lines


def realign_editor_timings_with_lines(
    editor_text: str,
    original_lines: Optional[List[List[Dict[str, Any]]]] = None,
    recognized_words: Optional[List[Dict[str, Any]]] = None,
    vocals_path: Optional[Path] = None,
) -> Tuple[str, List[List[Dict[str, Any]]]]:
    """
    Takes arbitrary editor text (with or without timestamps, with split lines or typo fixes),
    re-aligns all lines against acoustic speech words and vocal energy, and produces both fresh
    [MM:SS.cc -> MM:SS.cc] editor text AND the detailed list of word-timed karaoke lines.
    """
    words_pool = recognized_words
    if not words_pool and original_lines:
        words_pool = [dict(w) for line in original_lines for w in line]

    clean_lines = []
    for line_str in editor_text.splitlines():
        line_clean = line_str.strip()
        if not line_clean:
            continue
        m = re.match(r"^\[\s*([0-9:.,]+)\s*(?:->|–|-|to)\s*([0-9:.,]+)\s*\]\s*(.*)$", line_clean)
        if m:
            text_part = m.group(3).strip()
        else:
            text_part = line_clean
        if text_part.startswith("[") and text_part.endswith("]"):
            continue
        if text_part:
            clean_lines.append(text_part)

    clean_lines = sanitize_reference_lyrics(clean_lines)

    if not clean_lines:
        lines = editor_text_to_lines(editor_text, original_lines=original_lines, vocals_path=vocals_path)
        return editor_text, lines

    if words_pool:
        try:
            aligned_lines = align_words_to_reference_lines(
                words_pool,
                clean_lines,
                vocals_path=vocals_path,
                strict_repeats=False,
            )
            if aligned_lines:
                validate_karaoke_lines(aligned_lines)
                return lines_to_editor_text(aligned_lines), aligned_lines
        except Exception as e:
            print(f"[Karaoke] realign_editor_timings alignment fallback: {e}")

    lines = editor_text_to_lines(editor_text, original_lines=original_lines, vocals_path=vocals_path)
    return lines_to_editor_text(lines), lines


def realign_editor_timings(
    editor_text: str,
    original_lines: Optional[List[List[Dict[str, Any]]]] = None,
    recognized_words: Optional[List[Dict[str, Any]]] = None,
    vocals_path: Optional[Path] = None,
) -> str:
    """
    Takes arbitrary editor text (with or without timestamps, with split lines or typo fixes),
    re-aligns all lines against acoustic speech words and vocal energy, and produces fresh,
    clean, strictly monotonic [MM:SS.cc -> MM:SS.cc] timestamps for every line.
    """
    text, _ = realign_editor_timings_with_lines(
        editor_text=editor_text,
        original_lines=original_lines,
        recognized_words=recognized_words,
        vocals_path=vocals_path,
    )
    return text


def regroup_editor_lines(
    lines: List[List[Dict[str, Any]]],
    max_chars_per_line: int = 48,
) -> List[List[Dict[str, Any]]]:
    """
    Re-runs the 3-stage logical sentence & balanced clause grouping on an existing list of lines.
    Eliminates 2-3 word orphan lines (e.g. 'с качами,', 'у них,', 'и в рот.').
    """
    flat_words = [dict(w) for line in lines for w in line]
    if not flat_words:
        return []
    return regroup_words_into_logical_lines(flat_words, max_chars_per_line=max_chars_per_line)


def _find_best_line_split_index(words: List[Dict[str, Any]], allow_dangle_fallback: bool = False) -> int:
    """
    Finds the optimal split point within a sequence of words.
    Considers:
    - Russian dangling words (prepositions/particles/conjunctions) which cannot end a line.
    - Terminal punctuation (.!?;…) and clause punctuation (,—:-).
    - Acoustic gaps between words (singer breath / pauses).
    - Conjunctions starting the subsequent clause (и, а, но, что, как, etc.).
    - Visual character and word count balance.
    """
    n = len(words)
    if n < 2:
        return -1

    best_idx = -1
    best_score = float("inf")
    mid_w = n / 2.0
    total_chars = max(1, sum(len(w["text"]) for w in words) + n - 1)

    for i in range(1, n):
        prev_w = words[i - 1]["text"].strip()
        prev_bare = re.sub(r"[^\wа-яёА-ЯЁ]", "", prev_w).lower()
        prev_has_terminal_punct = bool(prev_w and prev_w[-1] in ".!?;…")

        if not allow_dangle_fallback:
            if not prev_has_terminal_punct and prev_bare in RUSSIAN_NO_DANGLE:
                continue

        score = 0.0

        if prev_has_terminal_punct:
            score -= 10.0
        elif prev_w and prev_w[-1] in ",—:-":
            score -= 6.0

        gap = words[i]["start"] - words[i - 1]["end"]
        if gap >= 0.35:
            score -= 6.0
        elif gap >= 0.15:
            score -= 3.5
        elif gap < 0:
            score += 1.5

        nxt_w = words[i]["text"].strip()
        nxt_bare = re.sub(r"[^\wа-яёА-ЯЁ]", "", nxt_w).lower()
        if nxt_bare in {
            "и", "а", "но", "да", "или", "либо", "что", "чтоб", "чтобы",
            "как", "где", "когда", "куда", "откуда", "почему", "зачем",
            "если", "хоть", "хотя", "ведь", "потому", "поэтому", "зато",
            "чем", "только", "лишь"
        }:
            score -= 4.0

        nxt_first = re.sub(r"^[^а-яёА-ЯЁa-zA-Z]+", "", nxt_w)[:1]
        if nxt_first.isupper():
            score -= 3.0

        left_chars = sum(len(w["text"]) for w in words[:i]) + max(0, i - 1)
        right_chars = sum(len(w["text"]) for w in words[i:]) + max(0, n - i - 1)
        char_balance = abs(left_chars - right_chars) / total_chars
        word_balance = abs(i - mid_w) / mid_w

        score += char_balance * 5.0 + word_balance * 3.0

        if n >= 4 and (i < 2 or (n - i) < 2):
            score += 8.0

        if allow_dangle_fallback and prev_bare in RUSSIAN_NO_DANGLE:
            score += 25.0

        if score < best_score:
            best_score = score
            best_idx = i

    if best_idx == -1 and not allow_dangle_fallback:
        return _find_best_line_split_index(words, allow_dangle_fallback=True)

    return best_idx


def split_single_long_line(
    words: List[Dict[str, Any]],
    max_chars: int = 38,
    max_words: int = 8,
) -> List[List[Dict[str, Any]]]:
    """
    Recursively splits a single line if it exceeds max_chars or max_words.
    Preserves exact word timestamps and avoids orphan 1-word fragments.
    """
    if not words:
        return []

    line_chars = sum(len(w["text"]) for w in words) + max(0, len(words) - 1)
    if len(words) <= max_words and line_chars <= max_chars:
        return [words]

    if len(words) < 4:
        # Avoid splitting lines into 1-word fragments unless severely long in characters
        if line_chars <= max_chars * 1.5 or len(words) < 2:
            return [words]

    idx = _find_best_line_split_index(words)
    if idx <= 0 or idx >= len(words):
        return [words]

    left = words[:idx]
    right = words[idx:]

    result: List[List[Dict[str, Any]]] = []
    result.extend(split_single_long_line(left, max_chars=max_chars, max_words=max_words))
    result.extend(split_single_long_line(right, max_chars=max_chars, max_words=max_words))
    return result


def split_long_editor_lines(
    lines: List[List[Dict[str, Any]]],
    max_chars: int = 38,
    max_words: int = 8,
) -> List[List[Dict[str, Any]]]:
    """
    Splits overly long lines in an existing line list into grammatically and musically
    balanced shorter karaoke lines, while preserving short and normal lines untouched.
    """
    result: List[List[Dict[str, Any]]] = []
    for line in lines:
        if not line:
            continue
        splits = split_single_long_line(line, max_chars=max_chars, max_words=max_words)
        result.extend(splits)
    return result


def refine_unaligned_vocal_slices(
    raw_words: List[Dict[str, Any]],
    reference_lyrics: Any,
    vocals_path: Optional[Path] = None,
    whisper_model: str = "large-v3-turbo",
    work_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """
    Detects unaligned vocal gaps where reference lyrics exist and vocals track has acoustic energy,
    but full-pass Whisper omitted transcription (e.g. folk vocalise, heavy EDM beat, autotune).
    Executes prompt-guided slice transcription on those windows and merges newly recognized words.
    """
    if not vocals_path or not Path(vocals_path).exists() or not reference_lyrics:
        return raw_words

    sanitized_ref = sanitize_reference_lyrics(reference_lyrics)
    if not sanitized_ref:
        return raw_words

    try:
        rms, hop_s = compute_vocal_rms_envelope(vocals_path)
        if rms is None or len(rms) == 0:
            return raw_words

        sorted_words = sorted(raw_words, key=lambda w: float(w.get("start", 0.0)))
        first_w_start = float(sorted_words[0]["start"]) if sorted_words else 0.0

        discovered_words: List[Dict[str, Any]] = []

        # 1. Intro vocal gap before first recognized word (> 4.5s)
        if first_w_start > 4.5:
            i_end = min(len(rms), int(first_w_start / hop_s))
            window = rms[0:i_end]
            global_p90 = float(np.percentile(rms, 90)) if len(rms) > 0 else 0.0
            thresh = max(0.008, global_p90 * 0.08)
            active_duration = float(np.sum(window > thresh)) * hop_s
            if active_duration >= 1.5:
                intro_ref_text = "\n".join(sanitized_ref[:8])
                try:
                    from karaoke.slice_editor import align_audio_slice
                    target_dir = work_dir or Path(vocals_path).parent
                    slice_words = align_audio_slice(
                        title="slice_refine_intro",
                        start=0.0,
                        end=first_w_start,
                        text=intro_ref_text,
                        mode="whisper",
                        work_dir=target_dir,
                    )
                    if slice_words:
                        discovered_words.extend(slice_words)
                except Exception as e:
                    print(f"[Karaoke] Intro slice refinement warning: {e}")

        if discovered_words:
            all_combined = list(raw_words)
            for dw in discovered_words:
                dw_s = float(dw["start"])
                dw_e = float(dw["end"])
                overlap = any(
                    float(rw["start"]) < dw_e - 0.05 and float(rw["end"]) > dw_s + 0.05
                    for rw in raw_words
                )
                if not overlap:
                    all_combined.append(dw)
            all_combined.sort(key=lambda w: (float(w.get("start", 0.0)), float(w.get("end", 0.0))))
            return all_combined
    except Exception as exc:
        print(f"[Karaoke] refine_unaligned_vocal_slices warning: {exc}")

    return raw_words
