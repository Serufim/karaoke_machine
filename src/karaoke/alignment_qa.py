import copy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from karaoke.aligner import (
    _build_syllable_timings_from_onsets,
    _rebalance_squashed_words,
    compute_vocal_rms_envelope,
    count_syllables,
    estimate_acoustic_syllable_timings,
    find_vocal_offset,
    find_vocal_onset,
    split_word_into_syllables,
    validate_karaoke_lines,
)


def _local_vocal_threshold(rms: np.ndarray, hop_s: float, t_start: float, t_end: float) -> float:
    i_s = max(0, int(t_start / hop_s))
    i_e = min(len(rms), int(t_end / hop_s))
    if i_e <= i_s:
        return 0.008
    win = rms[i_s:i_e]
    local_peak = float(np.percentile(win, 95)) if len(win) > 0 else 0.0
    return max(0.006, local_peak * 0.12)


def _score_single_line(
    line: List[Dict[str, Any]],
    prev_line_end: float,
    next_line_start: Optional[float],
    rms: Optional[np.ndarray],
    hop_s: float,
) -> Dict[str, Any]:
    """
    Evaluates a single karaoke line against the vocal RMS envelope.
    Returns per-line sub-scores (0..100) and diagnostic issue tags.
    """
    if not line:
        return {
            "score": 100.0,
            "onset_score": 100.0,
            "coverage_score": 100.0,
            "hang_score": 100.0,
            "tempo_score": 100.0,
            "issues": [],
        }

    issues: List[str] = []
    l_start = float(line[0]["start"])
    l_end = float(line[-1]["end"])

    # 1. Onset accuracy (30%): compare line[0].start to local vocal RMS onset
    onset_score = 100.0
    if rms is not None and len(rms) > 0:
        search_from = max(prev_line_end, l_start - 1.2)
        search_to = min(l_end, l_start + 1.2)
        if search_to > search_from + 0.25:
            thresh = _local_vocal_threshold(rms, hop_s, search_from, max(search_to, l_end))
            # Check if singing was already active BEFORE l_start (late entrance)
            i_pre_s = max(0, int(search_from / hop_s))
            i_ls = max(i_pre_s, min(len(rms), int(l_start / hop_s)))
            if i_ls - i_pre_s >= 6:
                pre_active = rms[i_pre_s:i_ls] > thresh
                # Count trailing active frames right before l_start
                late_frames = 0
                for val in reversed(pre_active):
                    if val:
                        late_frames += 1
                    else:
                        break
                late_s = late_frames * hop_s
                if late_s > 0.12:
                    issues.append("late_onset")
                    onset_score -= min(65.0, (late_s - 0.10) * 90.0)

            # Check if l_start sits on silence long before singing begins (early entrance)
            i_le = min(len(rms), int(min(l_end, l_start + 1.5) / hop_s))
            if i_le - i_ls >= 6:
                post_win = rms[i_ls:i_le] > thresh
                silent_frames = 0
                for val in post_win:
                    if not val:
                        silent_frames += 1
                    else:
                        break
                early_s = silent_frames * hop_s
                if early_s > 0.18:
                    issues.append("early_onset")
                    onset_score -= min(60.0, (early_s - 0.15) * 75.0)
    onset_score = max(0.0, min(100.0, onset_score))

    # 2. Coverage & mid-phrase continuity (30%)
    coverage_score = 100.0
    if rms is not None and len(rms) > 0 and l_end > l_start + 0.15:
        i_s = max(0, int(l_start / hop_s))
        i_e = min(len(rms), int(l_end / hop_s))
        if i_e > i_s + 4:
            thresh = _local_vocal_threshold(rms, hop_s, l_start, l_end)
            active_mask = rms[i_s:i_e] > thresh
            total_active = int(np.sum(active_mask))
            if total_active > 0:
                covered = np.zeros(i_e - i_s, dtype=bool)
                for w in line:
                    ws_i = max(0, int(float(w["start"]) / hop_s) - i_s)
                    we_i = min(i_e - i_s, int(round(float(w["end"]) / hop_s)) - i_s)
                    if we_i > ws_i:
                        covered[ws_i:we_i] = True
                cov_ratio = float(np.sum(active_mask & covered)) / total_active
                coverage_score = max(0.0, min(100.0, cov_ratio * 100.0))

        # Penalize artificial mid-line gaps > 0.22s where vocal RMS is active
        for w_curr, w_next in zip(line, line[1:]):
            gap = float(w_next["start"]) - float(w_curr["end"])
            if gap > 0.22:
                g_s = max(0, int(float(w_curr["end"]) / hop_s))
                g_e = min(len(rms), int(float(w_next["start"]) / hop_s))
                if g_e > g_s + 3:
                    thresh = _local_vocal_threshold(rms, hop_s, l_start, l_end)
                    gap_active_ratio = float(np.mean(rms[g_s:g_e] > thresh))
                    if gap_active_ratio >= 0.55:
                        if "mid_gap" not in issues:
                            issues.append("mid_gap")
                        coverage_score = max(0.0, coverage_score - min(35.0, gap * 35.0))

    # 3. Trailing silence / hang penalty (20%)
    hang_score = 100.0
    if rms is not None and len(rms) > 0:
        thresh = _local_vocal_threshold(rms, hop_s, l_start, l_end)
        for w in line:
            ws = float(w["start"])
            we = float(w["end"])
            if we - ws <= 0.25:
                continue
            i_ws = max(0, int(ws / hop_s))
            i_we = min(len(rms), int(we / hop_s))
            if i_we - i_ws >= 6:
                win = rms[i_ws:i_we] > thresh
                trail_silent = 0
                for val in reversed(win):
                    if not val:
                        trail_silent += 1
                    else:
                        break
                trail_s = trail_silent * hop_s
                if trail_s > 0.18:
                    if "trailing_silence" not in issues:
                        issues.append("trailing_silence")
                    hang_score -= min(45.0, (trail_s - 0.15) * 60.0)
        if next_line_start is not None and l_end > next_line_start + 0.01:
            issues.append("line_overlap")
            hang_score -= 40.0
    hang_score = max(0.0, min(100.0, hang_score))

    # 4. Tempo smoothness (20%): squashed words & extreme syllable-rate spikes
    tempo_score = 100.0
    syl_rates: List[float] = []
    for w in line:
        dur = max(0.01, float(w["end"]) - float(w["start"]))
        syls = max(1, int(w.get("syllables", count_syllables(w["text"]))))
        per_syl = dur / syls
        syl_rates.append(per_syl)
        if dur < max(0.11, syls * 0.075):
            if "squashed_word" not in issues:
                issues.append("squashed_word")
            tempo_score -= 22.0
    if len(syl_rates) >= 2:
        max_r = max(syl_rates)
        min_r = max(0.05, min(syl_rates))
        if max_r > 0.75 and (max_r / min_r) > 6.5:
            if "tempo_spike" not in issues:
                issues.append("tempo_spike")
            tempo_score -= min(25.0, (max_r / min_r - 6.0) * 4.0)
    tempo_score = max(0.0, min(100.0, tempo_score))

    overall = (
        0.30 * onset_score
        + 0.30 * coverage_score
        + 0.20 * hang_score
        + 0.20 * tempo_score
    )
    return {
        "score": round(overall, 1),
        "onset_score": round(onset_score, 1),
        "coverage_score": round(coverage_score, 1),
        "hang_score": round(hang_score, 1),
        "tempo_score": round(tempo_score, 1),
        "issues": issues,
    }


def evaluate_alignment_quality(
    lines: List[List[Dict[str, Any]]],
    vocals_path: Optional[Path],
    rms_cache: Optional[Tuple[Optional[np.ndarray], float]] = None,
) -> Dict[str, Any]:
    """
    Computes an objective 0-100% alignment accuracy score by comparing line/word timings
    against the isolated vocal RMS energy envelope.
    """
    if not lines:
        return {
            "overall_score": 0.0,
            "onset_score": 0.0,
            "coverage_score": 0.0,
            "hang_score": 0.0,
            "tempo_score": 0.0,
            "problem_lines": [],
            "line_scores": [],
        }

    rms, hop_s = rms_cache if rms_cache is not None else compute_vocal_rms_envelope(vocals_path)
    line_scores: List[Dict[str, Any]] = []
    problem_lines: List[Dict[str, Any]] = []

    for idx, line in enumerate(lines):
        prev_end = float(lines[idx - 1][-1]["end"]) if idx > 0 and lines[idx - 1] else 0.0
        next_start = float(lines[idx + 1][0]["start"]) if idx + 1 < len(lines) and lines[idx + 1] else None
        rep = _score_single_line(line, prev_end, next_start, rms, hop_s)
        rep["line_idx"] = idx
        line_scores.append(rep)
        if rep["score"] < 85.0 or rep["issues"]:
            problem_lines.append({
                "line_idx": idx,
                "score": rep["score"],
                "issues": rep["issues"],
            })

    n = len(line_scores)
    return {
        "overall_score": round(sum(r["score"] for r in line_scores) / n, 1),
        "onset_score": round(sum(r["onset_score"] for r in line_scores) / n, 1),
        "coverage_score": round(sum(r["coverage_score"] for r in line_scores) / n, 1),
        "hang_score": round(sum(r["hang_score"] for r in line_scores) / n, 1),
        "tempo_score": round(sum(r["tempo_score"] for r in line_scores) / n, 1),
        "problem_lines": problem_lines[:15],
        "line_scores": line_scores,
    }


def _refresh_word_syllable_timings(
    word: Dict[str, Any],
    rms: Optional[np.ndarray],
    hop_s: float,
) -> None:
    w_s, w_e = float(word["start"]), float(word["end"])
    sylls = split_word_into_syllables(word["text"])
    if len(sylls) <= 1:
        word.pop("syllable_timings", None)
        return
    st = word.get("syllable_timings")
    if isinstance(st, list) and len(st) == len(sylls) and "".join(str(x.get("text", "")) for x in st) == word["text"]:
        onsets = [float(x["start"]) for x in st]
        onsets[0] = w_s
        word["syllable_timings"] = _build_syllable_timings_from_onsets(sylls, onsets, w_s, w_e)
    elif rms is not None and len(rms) > 0:
        word["syllable_timings"] = estimate_acoustic_syllable_timings(word["text"], w_s, w_e, rms, hop_s)


def _optimize_line_pass(
    line: List[Dict[str, Any]],
    prev_end: float,
    next_start: Optional[float],
    rms: Optional[np.ndarray],
    hop_s: float,
    issues: List[str],
) -> None:
    """Applies targeted acoustic corrections to a single line based on detected QA issues."""
    if not line:
        return

    # 1. Fix late or early onset on line[0]
    if rms is not None and len(rms) > 0 and ("late_onset" in issues or "early_onset" in issues):
        w0 = line[0]
        w0_s, w0_e = float(w0["start"]), float(w0["end"])
        search_from = max(prev_end + 0.02, w0_s - 0.90)
        search_to = min(w0_e - 0.12, w0_s + 0.90)
        if search_to > search_from + 0.20:
            real_onset = find_vocal_onset(rms, hop_s, search_from, w0_e, fallback=w0_s)
            real_onset = max(prev_end + 0.02, min(w0_e - 0.12, round(real_onset, 2)))
            if abs(real_onset - w0_s) >= 0.06:
                w0["start"] = real_onset

    # 2. Close artificial mid-line gaps where vocals are continuously active
    if rms is not None and len(rms) > 0 and "mid_gap" in issues:
        l_start = float(line[0]["start"])
        l_end = float(line[-1]["end"])
        thresh = _local_vocal_threshold(rms, hop_s, l_start, l_end)
        for idx in range(len(line) - 1):
            w_c, w_n = line[idx], line[idx + 1]
            gap = float(w_n["start"]) - float(w_c["end"])
            if gap > 0.20:
                g_s = max(0, int(float(w_c["end"]) / hop_s))
                g_e = min(len(rms), int(float(w_n["start"]) / hop_s))
                if g_e > g_s + 2 and float(np.mean(rms[g_s:g_e] > thresh)) >= 0.55:
                    s_c = max(1, int(w_c.get("syllables", count_syllables(w_c["text"]))))
                    s_n = max(1, int(w_n.get("syllables", count_syllables(w_n["text"]))))
                    split_t = round(float(w_c["end"]) + gap * (s_c / (s_c + s_n)), 2)
                    w_c["end"] = split_t
                    w_n["start"] = split_t

    # 3. Trim trailing silence on words
    if rms is not None and len(rms) > 0 and "trailing_silence" in issues:
        for idx, w in enumerate(line):
            ws, we = float(w["start"]), float(w["end"])
            if we - ws > 0.35:
                real_off = find_vocal_offset(rms, hop_s, ws, we, min_silence_s=0.16)
                if ws + 0.14 <= real_off < we - 0.12:
                    w["end"] = round(real_off, 2)

    # 4. Rebalance squashed words
    _rebalance_squashed_words(line)

    # 5. Enforce monotonic bounds inside line and against neighbors
    cursor = prev_end
    for idx, w in enumerate(line):
        ws = max(cursor, float(w["start"]))
        we = max(ws + 0.08, float(w["end"]))
        if next_start is not None and idx == len(line) - 1 and we > next_start:
            if next_start - ws >= 0.08:
                we = next_start
        w["start"] = round(ws, 2)
        w["end"] = round(we, 2)
        cursor = w["end"]
        _refresh_word_syllable_timings(w, rms, hop_s)


ANCHOR_TOLERANCE_S = 0.30


def _norm_word(text: str) -> str:
    return "".join(ch for ch in str(text).lower().replace("ё", "е") if ch.isalnum())


def compute_line_anchors(
    lines: List[List[Dict[str, Any]]],
    recognized_words: Optional[List[Dict[str, Any]]],
) -> List[Optional[float]]:
    """
    Returns, for each line, the raw Whisper start time of its first word (or None).
    Whisper word onsets proved to be the most reliable reference on dense sung vocals,
    so they are used as anchors that downstream refinement may not drift away from.
    """
    anchors: List[Optional[float]] = []
    rw = [w for w in (recognized_words or []) if "start" in w and "text" in w]
    for line in lines:
        if not line or not rw:
            anchors.append(None)
            continue
        l_s = float(line[0]["start"])
        target = _norm_word(line[0]["text"])
        best: Optional[float] = None
        best_d = 1e9
        for w in rw:
            ws = float(w["start"])
            d = abs(ws - l_s)
            if d > 2.5:
                continue
            if target and _norm_word(w["text"]) == target and d < best_d:
                best, best_d = ws, d
        anchors.append(round(best, 2) if best is not None else None)
    return anchors


def _violates_anchor(
    line: List[Dict[str, Any]],
    anchor: Optional[float],
    rms: Optional[np.ndarray],
    hop_s: float,
) -> bool:
    """True when the line start drifted > ANCHOR_TOLERANCE_S from the Whisper onset without acoustic support."""
    if anchor is None or not line:
        return False
    l_s = float(line[0]["start"])
    drift = l_s - anchor
    if abs(drift) <= ANCHOR_TOLERANCE_S:
        return False
    # Moving later is acceptable only if the skipped region [anchor, l_s] is mostly silence
    if drift > 0 and rms is not None and len(rms) > 0:
        i_a = max(0, int(anchor / hop_s))
        i_b = min(len(rms), int(l_s / hop_s))
        if i_b > i_a:
            thresh = _local_vocal_threshold(rms, hop_s, anchor - 1.0, l_s + 1.0)
            if float(np.mean(rms[i_a:i_b] > thresh)) < 0.30:
                return False
    return True


def _line_differs(a: List[Dict[str, Any]], b: List[Dict[str, Any]], min_shift: float = 0.15) -> bool:
    if len(a) != len(b):
        return True
    return any(
        abs(float(x["start"]) - float(y["start"])) >= min_shift or abs(float(x["end"]) - float(y["end"])) >= min_shift
        for x, y in zip(a, b)
    )


def whisper_line_candidate(
    line: List[Dict[str, Any]],
    recognized_words: Optional[List[Dict[str, Any]]],
) -> Optional[List[Dict[str, Any]]]:
    """Rebuilds `line` with raw Whisper word timings when every word can be matched (same text, nearby time)."""
    rw = [w for w in (recognized_words or []) if "start" in w and "end" in w and "text" in w]
    if not line or not rw:
        return None
    out: List[Dict[str, Any]] = []
    cursor = -1e9
    for w in line:
        key = _norm_word(w["text"])
        ws = float(w["start"])
        best = None
        best_d = 1e9
        for r in rw:
            rs = float(r["start"])
            if rs < cursor - 0.01:
                continue
            d = abs(rs - ws)
            if d <= 2.5 and key and _norm_word(r["text"]) == key and d < best_d:
                best, best_d = r, d
        if best is None:
            return None
        nw = dict(w)
        nw["start"] = round(float(best["start"]), 2)
        nw["end"] = round(max(float(best["start"]) + 0.08, float(best["end"])), 2)
        nw.pop("syllable_timings", None)
        out.append(nw)
        cursor = nw["end"]
    return out


def optimize_alignment_to_target(
    lines: List[List[Dict[str, Any]]],
    vocals_path: Optional[Path],
    ctc_lines: Optional[List[List[Dict[str, Any]]]] = None,
    target_score: float = 90.0,
    max_iters: int = 4,
    recognized_words: Optional[List[Dict[str, Any]]] = None,
    locked_lines: Optional[Dict[int, List[Dict[str, Any]]]] = None,
    bad_lines: Optional[Dict[int, List[Dict[str, Any]]]] = None,
) -> Tuple[List[List[Dict[str, Any]]], Dict[str, Any]]:
    """
    Evaluates alignment quality against vocals.wav and iteratively optimizes timings
    until overall_score >= target_score (or max_iters reached), always preserving the best state.
    If `ctc_lines` is provided, selects CTC per-line only when it strictly improves the line score.

    - `recognized_words`: raw Whisper words; line starts may not drift > 0.30s from them.
    - `locked_lines`: {line_idx: timings} the user marked as good; restored verbatim and never touched.
    - `bad_lines`: {line_idx: timings} the user marked as bad; a different candidate is preferred.
    """
    if not lines:
        return lines, evaluate_alignment_quality(lines, vocals_path)

    rms, hop_s = compute_vocal_rms_envelope(vocals_path)
    rms_cache = (rms, hop_s)
    locked = dict(locked_lines or {})
    bad = dict(bad_lines or {})

    best_lines = copy.deepcopy(lines)
    for idx, timings in locked.items():
        if 0 <= idx < len(best_lines) and len(timings) == len(best_lines[idx]):
            best_lines[idx] = copy.deepcopy(timings)
    anchors = compute_line_anchors(best_lines, recognized_words)

    # Anchor repair: lines that already drifted away from the Whisper onset (e.g. an earlier
    # optimizer pulled them into the previous line's tail) are restored from raw Whisper timings.
    anchor_repaired: List[int] = []
    for idx, line in enumerate(best_lines):
        if idx in locked or not _violates_anchor(line, anchors[idx], rms, hop_s):
            continue
        cand = whisper_line_candidate(line, recognized_words)
        if not cand:
            continue
        prev_e = float(best_lines[idx - 1][-1]["end"]) if idx > 0 and best_lines[idx - 1] else 0.0
        next_s = float(best_lines[idx + 1][0]["start"]) if idx + 1 < len(best_lines) and best_lines[idx + 1] else None
        if float(cand[0]["start"]) < prev_e - 0.01:
            continue
        if next_s is not None and float(cand[-1]["end"]) > next_s + 0.01:
            cand[-1]["end"] = round(max(float(cand[-1]["start"]) + 0.08, next_s), 2)
        for w in cand:
            _refresh_word_syllable_timings(w, rms, hop_s)
        best_lines[idx] = cand
        anchor_repaired.append(idx)

    def _ok(idx: int, cand: List[Dict[str, Any]]) -> bool:
        if _violates_anchor(cand, anchors[idx], rms, hop_s):
            return False
        if idx in bad and not _line_differs(cand, bad[idx]):
            return False
        return True

    # Step 0: Per-line candidate selection (Baseline Whisper+RMS vs CTC MMS_FA)
    if ctc_lines and len(ctc_lines) == len(best_lines):
        merged: List[List[Dict[str, Any]]] = []
        for idx, (base_l, ctc_l) in enumerate(zip(best_lines, ctc_lines)):
            if idx in locked:
                merged.append(copy.deepcopy(base_l))
                continue
            prev_e = float(merged[-1][-1]["end"]) if merged and merged[-1] else 0.0
            next_s = float(best_lines[idx + 1][0]["start"]) if idx + 1 < len(best_lines) and best_lines[idx + 1] else None
            base_rep = _score_single_line(base_l, prev_e, next_s, rms, hop_s)
            ctc_rep = _score_single_line(ctc_l, prev_e, next_s, rms, hop_s)
            # Only adopt CTC if it strictly improves the line by >= 1.5 pts and doesn't violate prev_e
            # (bad-marked lines accept any CTC variant that differs from the rejected timings and is not worse)
            min_gain = -1.0 if (idx in bad and not _line_differs(base_l, bad[idx])) else 1.5
            if (
                ctc_l
                and len(ctc_l) == len(base_l)
                and float(ctc_l[0]["start"]) >= prev_e - 0.01
                and ctc_rep["score"] >= base_rep["score"] + min_gain
                and _ok(idx, ctc_l)
            ):
                merged.append(copy.deepcopy(ctc_l))
            else:
                merged.append(copy.deepcopy(base_l))
        try:
            validate_karaoke_lines(merged)
            best_lines = merged
        except Exception:
            pass

    best_report = evaluate_alignment_quality(best_lines, vocals_path, rms_cache=rms_cache)
    pending_bad = [i for i in bad if 0 <= i < len(best_lines) and not _line_differs(best_lines[i], bad[i])]
    if rms is None or len(rms) == 0 or (best_report["overall_score"] >= target_score and not pending_bad):
        return best_lines, _annotate_report(best_report, locked, bad, best_lines, anchor_repaired)

    current_lines = copy.deepcopy(best_lines)
    for _ in range(max_iters):
        cur_report = evaluate_alignment_quality(current_lines, vocals_path, rms_cache=rms_cache)
        pending_bad = [i for i in bad if 0 <= i < len(current_lines) and not _line_differs(current_lines[i], bad[i])]
        if cur_report["overall_score"] >= target_score and not pending_bad:
            break

        improved_any = False
        for idx, line in enumerate(current_lines):
            if idx in locked:
                continue
            l_rep = cur_report["line_scores"][idx]
            forced_bad = idx in pending_bad
            if l_rep["score"] >= target_score and not l_rep["issues"] and not forced_bad:
                continue
            prev_e = float(current_lines[idx - 1][-1]["end"]) if idx > 0 and current_lines[idx - 1] else 0.0
            next_s = float(current_lines[idx + 1][0]["start"]) if idx + 1 < len(current_lines) and current_lines[idx + 1] else None

            candidate_line = copy.deepcopy(line)
            issues = list(l_rep["issues"])
            if forced_bad:
                issues = list(set(issues) | {"late_onset", "mid_gap", "trailing_silence"})
            _optimize_line_pass(candidate_line, prev_e, next_s, rms, hop_s, issues)
            if not _ok(idx, candidate_line):
                continue
            new_rep = _score_single_line(candidate_line, prev_e, next_s, rms, hop_s)
            min_gain = -3.0 if forced_bad else 0.1
            if new_rep["score"] > l_rep["score"] + min_gain:
                current_lines[idx] = candidate_line
                improved_any = True

        if not improved_any:
            break

        try:
            validate_karaoke_lines(current_lines)
            new_full_report = evaluate_alignment_quality(current_lines, vocals_path, rms_cache=rms_cache)
            fixed_bad = sum(1 for i in bad if 0 <= i < len(current_lines) and _line_differs(current_lines[i], bad[i]))
            prev_fixed = sum(1 for i in bad if 0 <= i < len(best_lines) and _line_differs(best_lines[i], bad[i]))
            if new_full_report["overall_score"] > best_report["overall_score"] or fixed_bad > prev_fixed:
                best_lines = copy.deepcopy(current_lines)
                best_report = new_full_report
        except Exception:
            break

    validate_karaoke_lines(best_lines)
    return best_lines, _annotate_report(best_report, locked, bad, best_lines, anchor_repaired)


def _annotate_report(
    report: Dict[str, Any],
    locked: Dict[int, List[Dict[str, Any]]],
    bad: Dict[int, List[Dict[str, Any]]],
    lines: List[List[Dict[str, Any]]],
    anchor_repaired: Optional[List[int]] = None,
) -> Dict[str, Any]:
    report = dict(report)
    report["anchor_repaired_lines"] = sorted(anchor_repaired or [])
    report["locked_lines"] = sorted(locked.keys())
    report["changed_bad_lines"] = sorted(
        i for i in bad if 0 <= i < len(lines) and _line_differs(lines[i], bad[i])
    )
    report["unchanged_bad_lines"] = sorted(
        i for i in bad if 0 <= i < len(lines) and not _line_differs(lines[i], bad[i])
    )
    return report


def format_alignment_report_summary(report: Optional[Dict[str, Any]]) -> str:
    """Formats a concise Russian UI summary string for alignment QA accuracy."""
    if not report or not isinstance(report, dict) or "overall_score" not in report:
        return ""
    return (
        f"🎯 Точность таймингов: {report['overall_score']:.1f}% "
        f"(вступления: {report.get('onset_score', 0):.0f}%, "
        f"покрытие: {report.get('coverage_score', 0):.0f}%, "
        f"темп: {report.get('tempo_score', 0):.0f}%)"
    )
