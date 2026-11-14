"""
Timing history snapshots and per-line user marks ("good" / "bad").

Every time a project's `lines` are about to be overwritten (regeneration, auto-optimization,
acoustic realign, restore), the previous timings are saved as a snapshot in
`<work_dir>/<title>_timings_history/`. Users can compare versions, restore any of them, and
mark individual lines as good (locked across regenerations) or bad (must change next time).

Marks are keyed by normalized line text + approximate time (not by line index), so they
survive regenerations that split lines differently.
"""
import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MAX_SNAPSHOTS = 30
MARK_MATCH_WINDOW_S = 3.0

REASON_LABELS = {
    "regenerate": "перегенерация",
    "optimize": "автоподгонка",
    "realign": "пересчёт таймингов",
    "realign_vocals": "по вокалу",
    "restore": "до восстановления",
    "manual": "ручное сохранение",
}


def history_dir(work_dir: Path, title: str) -> Path:
    return Path(work_dir) / f"{title}_timings_history"


def normalize_line_text(line: List[Dict[str, Any]]) -> str:
    text = " ".join(str(w.get("text", "")) for w in line).lower().replace("ё", "е")
    return re.sub(r"[^\w\s]", "", text).strip()


def _marks_summary(marks: Optional[List[Dict[str, Any]]]) -> Dict[str, int]:
    marks = marks or []
    return {
        "good": sum(1 for m in marks if m.get("mark") == "good"),
        "bad": sum(1 for m in marks if m.get("mark") == "bad"),
    }


def save_snapshot(work_dir: Path, title: str, state: Dict[str, Any], reason: str) -> Optional[Dict[str, Any]]:
    """Saves the current `lines` of `state` as a history snapshot. Returns snapshot meta or None."""
    lines = state.get("lines") or []
    if not lines:
        return None
    hdir = history_dir(work_dir, title)
    hdir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    snap_id = now.strftime("%Y%m%d-%H%M%S-%f")[:-3] + f"_{reason}"
    report = state.get("alignment_report") or {}
    marks = state.get("line_marks") or []
    # Store per-line marks resolved against these lines so the snapshot is self-describing
    resolved = resolve_marks(lines, marks)
    snapshot = {
        "id": snap_id,
        "created_at": now.isoformat(timespec="seconds"),
        "reason": reason,
        "reason_label": REASON_LABELS.get(reason, reason),
        "lines": copy.deepcopy(lines),
        "editor_text": state.get("editor_text", ""),
        "alignment_report": {k: v for k, v in report.items() if k != "line_scores"},
        "line_marks": copy.deepcopy(marks),
        "line_mark_by_idx": {str(k): v for k, v in resolved.items()},
        "marks_summary": _marks_summary(marks),
        "line_count": len(lines),
    }
    (hdir / f"{snap_id}.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")

    files = sorted(hdir.glob("*.json"))
    for old in files[:-MAX_SNAPSHOTS]:
        try:
            old.unlink()
        except OSError:
            pass
    return _meta(snapshot)


def _meta(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    report = snapshot.get("alignment_report") or {}
    return {
        "id": snapshot["id"],
        "created_at": snapshot.get("created_at"),
        "reason": snapshot.get("reason"),
        "reason_label": snapshot.get("reason_label") or REASON_LABELS.get(snapshot.get("reason", ""), ""),
        "overall_score": report.get("overall_score"),
        "marks_summary": snapshot.get("marks_summary") or {"good": 0, "bad": 0},
        "line_count": snapshot.get("line_count", len(snapshot.get("lines") or [])),
    }


def list_snapshots(work_dir: Path, title: str) -> List[Dict[str, Any]]:
    hdir = history_dir(work_dir, title)
    if not hdir.exists():
        return []
    metas = []
    for f in sorted(hdir.glob("*.json"), reverse=True):
        try:
            metas.append(_meta(json.loads(f.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return metas


def load_snapshot(work_dir: Path, title: str, snap_id: str) -> Optional[Dict[str, Any]]:
    if not re.fullmatch(r"[\w\-]+", snap_id or ""):
        return None
    f = history_dir(work_dir, title) / f"{snap_id}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def match_line(
    target: List[Dict[str, Any]],
    candidates: List[List[Dict[str, Any]]],
    window_s: float = MARK_MATCH_WINDOW_S,
) -> Optional[int]:
    """Finds the candidate line with the same normalized text and the nearest start (within window)."""
    if not target:
        return None
    key = normalize_line_text(target)
    t_s = float(target[0]["start"])
    best, best_d = None, 1e9
    for idx, cand in enumerate(candidates):
        if not cand or normalize_line_text(cand) != key:
            continue
        d = abs(float(cand[0]["start"]) - t_s)
        if d <= window_s and d < best_d:
            best, best_d = idx, d
    return best


def resolve_marks(lines: List[List[Dict[str, Any]]], marks: Optional[List[Dict[str, Any]]]) -> Dict[int, str]:
    """Maps stored marks onto current line indices (text + nearest time)."""
    result: Dict[int, str] = {}
    for m in marks or []:
        key = m.get("text", "")
        m_s = float(m.get("start", 0.0))
        best, best_d = None, 1e9
        for idx, ln in enumerate(lines):
            if not ln or normalize_line_text(ln) != key:
                continue
            d = abs(float(ln[0]["start"]) - m_s)
            if d <= MARK_MATCH_WINDOW_S and d < best_d and idx not in result:
                best, best_d = idx, d
        if best is not None:
            result[best] = m.get("mark", "")
    return result


def set_line_mark(
    lines: List[List[Dict[str, Any]]],
    marks: Optional[List[Dict[str, Any]]],
    line_idx: int,
    mark: Optional[str],
) -> List[Dict[str, Any]]:
    """Sets/clears the mark of `lines[line_idx]`, storing a copy of its timings. Returns new marks list."""
    if not (0 <= line_idx < len(lines)) or not lines[line_idx]:
        raise IndexError(f"line_idx {line_idx} out of range")
    line = lines[line_idx]
    key = normalize_line_text(line)
    l_s = float(line[0]["start"])
    kept = []
    for m in marks or []:
        same = m.get("text") == key and abs(float(m.get("start", 0.0)) - l_s) <= MARK_MATCH_WINDOW_S
        if not same:
            kept.append(m)
    if mark in ("good", "bad"):
        kept.append({
            "text": key,
            "start": round(l_s, 2),
            "end": round(float(line[-1]["end"]), 2),
            "mark": mark,
            "timings": copy.deepcopy(line),
            "marked_at": datetime.now().isoformat(timespec="seconds"),
        })
    return kept


def marks_to_constraints(
    lines: List[List[Dict[str, Any]]],
    marks: Optional[List[Dict[str, Any]]],
) -> Tuple[Dict[int, List[Dict[str, Any]]], Dict[int, List[Dict[str, Any]]]]:
    """
    Converts stored marks into optimizer constraints for the given (new) lines:
    - locked: {idx: good timings} — restored verbatim (only when word count matches)
    - bad:    {idx: rejected timings} — the optimizer must produce something different
    """
    locked: Dict[int, List[Dict[str, Any]]] = {}
    bad: Dict[int, List[Dict[str, Any]]] = {}
    used: set = set()
    for m in marks or []:
        timings = m.get("timings") or []
        if not timings:
            continue
        idx = match_line(timings, [ln if i not in used else [] for i, ln in enumerate(lines)])
        if idx is None or len(lines[idx]) != len(timings):
            continue
        used.add(idx)
        if m.get("mark") == "good":
            locked[idx] = copy.deepcopy(timings)
        elif m.get("mark") == "bad":
            bad[idx] = copy.deepcopy(timings)
    return locked, bad


def refresh_mark_timings(lines: List[List[Dict[str, Any]]], marks: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    After a new version is produced, keeps 'good' marks pointing at the (locked) timings and
    re-anchors marks onto the new line positions. 'bad' marks keep the rejected timings so the
    next regeneration still avoids them, but their anchor start follows the new line.
    """
    out = []
    resolved = resolve_marks(lines, marks)
    by_key = {}
    for idx, mk in resolved.items():
        by_key.setdefault((normalize_line_text(lines[idx]), mk), []).append(idx)
    for m in marks or []:
        m2 = dict(m)
        cands = by_key.get((m.get("text"), m.get("mark")), [])
        if cands:
            idx = min(cands, key=lambda i: abs(float(lines[i][0]["start"]) - float(m.get("start", 0.0))))
            m2["start"] = round(float(lines[idx][0]["start"]), 2)
            m2["end"] = round(float(lines[idx][-1]["end"]), 2)
            if m.get("mark") == "good":
                m2["timings"] = copy.deepcopy(lines[idx])
        out.append(m2)
    return out


def diff_lines(
    old_lines: List[List[Dict[str, Any]]],
    new_lines: List[List[Dict[str, Any]]],
) -> List[Optional[Dict[str, float]]]:
    """For each new line, returns start/end shift (seconds) vs the matching old line, or None if unmatched."""
    result: List[Optional[Dict[str, float]]] = []
    for ln in new_lines:
        idx = match_line(ln, old_lines)
        if idx is None:
            result.append(None)
            continue
        old = old_lines[idx]
        result.append({
            "start_shift": round(float(ln[0]["start"]) - float(old[0]["start"]), 2),
            "end_shift": round(float(ln[-1]["end"]) - float(old[-1]["end"]), 2),
            "max_word_shift": round(
                max(
                    (abs(float(a["start"]) - float(b["start"])) for a, b in zip(ln, old)),
                    default=0.0,
                ),
                2,
            ) if len(ln) == len(old) else None,
        })
    return result


def find_changed_line_indices(
    old_lines: List[List[Dict[str, Any]]],
    new_lines: List[List[Dict[str, Any]]],
    min_shift: float = 0.05,
) -> List[int]:
    """Returns indices in `new_lines` whose start, end, or text changed vs `old_lines`."""
    changed: List[int] = []
    for idx, ln in enumerate(new_lines):
        if not ln:
            continue
        old = old_lines[idx] if idx < len(old_lines) else None
        if not old or normalize_line_text(old) != normalize_line_text(ln):
            m_idx = match_line(ln, old_lines)
            old = old_lines[m_idx] if m_idx is not None else None
        if not old:
            changed.append(idx)
            continue
        if (
            normalize_line_text(old) != normalize_line_text(ln)
            or abs(float(ln[0]["start"]) - float(old[0]["start"])) >= min_shift
            or abs(float(ln[-1]["end"]) - float(old[-1]["end"])) >= min_shift
        ):
            changed.append(idx)
    return changed
