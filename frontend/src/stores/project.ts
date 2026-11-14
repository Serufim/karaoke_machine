import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  ProjectMeta,
  ProjectState,
  VocalInterval,
  FxInterval,
  EmojiInterval,
  TimingSnapshotMeta,
  LineTimingDiff,
} from '@/types'

function formatEditorTime(sec: number): string {
  if (!sec || isNaN(sec) || sec < 0) sec = 0
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  const cs = Math.floor((sec % 1) * 100)
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}.${cs.toString().padStart(2, '0')}`
}

function rebuildEditorTextFromLines(lines: any[]): string {
  return lines.map((line) => {
    let s = 0, e = 0, text = ''
    if (Array.isArray(line) && line.length > 0) {
      s = line[0]?.start ?? 0
      e = line[line.length - 1]?.end ?? 0
      text = line.map((w: any) => w.text || '').join(' ').trim()
    } else if (line) {
      s = line.start ?? 0
      e = line.end ?? 0
      text = line.text ?? ''
    }
    return `[${formatEditorTime(s)} -> ${formatEditorTime(e)}] ${text}`
  }).join('\n')
}

export const useProjectStore = defineStore('project', () => {
  const projects = ref<ProjectMeta[]>([])
  const currentProject = ref<ProjectState | null>(null)
  const isLoading = ref<boolean>(false)
  const isDirty = ref<boolean>(false)
  const errorMessage = ref<string | null>(null)
  const coverTimestamp = ref<number>(Date.now())
  const mediaTimestamp = ref<number>(Date.now())

  // Undo/Redo history of intervals & editor_text & lines
  const history = ref<string[]>([])
  const historyIndex = ref<number>(-1)

  const hasProject = computed(() => !!currentProject.value)
  const duration = computed(() => currentProject.value?.duration || 0)
  const title = computed(() => currentProject.value?.title || '')

  function pushHistory() {
    if (!currentProject.value) return
    const snapshot = JSON.stringify({
      vocal_intervals: currentProject.value.vocal_intervals,
      fx_intervals: currentProject.value.fx_intervals,
      emoji_intervals: currentProject.value.emoji_intervals || [],
      editor_text: currentProject.value.editor_text,
      lines: currentProject.value.lines,
    })
    // Truncate future if branched
    if (historyIndex.value < history.value.length - 1) {
      history.value = history.value.slice(0, historyIndex.value + 1)
    }
    history.value.push(snapshot)
    if (history.value.length > 30) history.value.shift()
    historyIndex.value = history.value.length - 1
    isDirty.value = true
  }

  function undo() {
    if (historyIndex.value > 0 && currentProject.value) {
      historyIndex.value--
      const state = JSON.parse(history.value[historyIndex.value])
      currentProject.value.vocal_intervals = state.vocal_intervals
      currentProject.value.fx_intervals = state.fx_intervals
      currentProject.value.emoji_intervals = state.emoji_intervals || []
      currentProject.value.editor_text = state.editor_text
      if (state.lines) currentProject.value.lines = state.lines
      isDirty.value = true
    }
  }

  function redo() {
    if (historyIndex.value < history.value.length - 1 && currentProject.value) {
      historyIndex.value++
      const state = JSON.parse(history.value[historyIndex.value])
      currentProject.value.vocal_intervals = state.vocal_intervals
      currentProject.value.fx_intervals = state.fx_intervals
      currentProject.value.emoji_intervals = state.emoji_intervals || []
      currentProject.value.editor_text = state.editor_text
      if (state.lines) currentProject.value.lines = state.lines
      isDirty.value = true
    }
  }

  async function fetchProjects() {
    try {
      const res = await fetch('/api/projects')
      if (!res.ok) throw new Error('Ошибка получения списка проектов')
      const data = await res.json()
      projects.value = data.projects || []
    } catch (e: any) {
      errorMessage.value = e.message
    }
  }

  async function loadProject(projectTitle: string) {
    if (!projectTitle) return
    isLoading.value = true
    errorMessage.value = null
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(projectTitle)}`)
      if (!res.ok) throw new Error(`Не удалось загрузить проект ${projectTitle}`)
      const data: ProjectState = await res.json()
      data.emoji_intervals = data.emoji_intervals || []
      currentProject.value = data
      pendingRealignIndices.value = []
      liveOverlayEnabled.value = false
      history.value = []
      historyIndex.value = -1
      pushHistory()
      isDirty.value = false
      mediaTimestamp.value = Date.now()
      await fetchTimingHistory(projectTitle)
    } catch (e: any) {
      errorMessage.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function saveProject() {
    if (!currentProject.value) return
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(currentProject.value.title)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          vocal_intervals: currentProject.value.vocal_intervals,
          fx_intervals: currentProject.value.fx_intervals,
          emoji_intervals: currentProject.value.emoji_intervals || [],
          editor_text: currentProject.value.editor_text,
          lines: currentProject.value.lines,
        }),
      })
      if (!res.ok) throw new Error('Ошибка сохранения проекта')
      isDirty.value = false
    } catch (e: any) {
      errorMessage.value = e.message
    }
  }

  function setVocalIntervals(intervals: VocalInterval[]) {
    if (!currentProject.value) return
    currentProject.value.vocal_intervals = intervals
    pushHistory()
  }

  function setFxIntervals(intervals: FxInterval[]) {
    if (!currentProject.value) return
    currentProject.value.fx_intervals = intervals
    pushHistory()
  }

  function setEmojiIntervals(intervals: EmojiInterval[]) {
    if (!currentProject.value) return
    currentProject.value.emoji_intervals = intervals
    pushHistory()
  }

  function setEditorText(text: string) {
    if (!currentProject.value) return
    currentProject.value.editor_text = text
    pushHistory()
  }

  const pendingRealignIndices = ref<number[]>([])
  const liveOverlayEnabled = ref<boolean>(false)

  function addPendingRealign(lineIndex: number) {
    if (!pendingRealignIndices.value.includes(lineIndex)) {
      pendingRealignIndices.value = [...pendingRealignIndices.value, lineIndex].sort((a, b) => a - b)
    }
  }

  function removePendingRealign(lineIndex: number) {
    pendingRealignIndices.value = pendingRealignIndices.value.filter((i) => i !== lineIndex)
  }

  function clearPendingRealign() {
    pendingRealignIndices.value = []
  }

  function rescaleLineInPlace(line: any, newStart: number, newEnd: number) {
    if (!line) return
    if (Array.isArray(line) && line.length > 0) {
      const oldStart = Number(line[0].start ?? 0)
      const oldEnd = Number(line[line.length - 1].end ?? oldStart + 1.0)
      const oldDur = Math.max(0.01, oldEnd - oldStart)
      const newDur = Math.max(0.08 * line.length, newEnd - newStart)

      for (const w of line) {
        const relS = (Number(w.start ?? oldStart) - oldStart) / oldDur
        const relE = (Number(w.end ?? oldEnd) - oldStart) / oldDur
        w.start = Number((newStart + relS * newDur).toFixed(2))
        w.end = Number((newStart + relE * newDur).toFixed(2))
        if (Array.isArray(w.syllable_timings)) {
          for (const st of w.syllable_timings) {
            const sRel = (Number(st.start ?? oldStart) - oldStart) / oldDur
            const eRel = (Number(st.end ?? oldEnd) - oldStart) / oldDur
            st.start = Number((newStart + sRel * newDur).toFixed(3))
            st.end = Number((newStart + eRel * newDur).toFixed(3))
          }
        }
      }
    } else {
      line.start = newStart
      line.end = newEnd
    }
  }

  function shiftLineTiming(lineIndex: number, newStart: number, newEnd: number) {
    if (!currentProject.value || !currentProject.value.lines) return
    const lines = currentProject.value.lines
    const line = lines[lineIndex]
    if (!line) return

    newStart = Math.max(0, Number(newStart.toFixed(2)))
    newEnd = Math.max(newStart + 0.15, Number(newEnd.toFixed(2)))

    // Trim overlapping neighbours so user-stretched bounds are preserved across realign/rebuild
    if (lineIndex > 0 && Array.isArray(lines[lineIndex - 1]) && lines[lineIndex - 1].length > 0) {
      const prev = lines[lineIndex - 1]
      const prevStart = Number(prev[0].start ?? 0)
      const prevEnd = Number(prev[prev.length - 1].end ?? 0)
      if (prevEnd > newStart) {
        const minPrevDur = 0.08 * prev.length
        if (newStart - prevStart >= minPrevDur) {
          rescaleLineInPlace(prev, prevStart, newStart)
        } else {
          newStart = Number((prevStart + minPrevDur).toFixed(2))
          rescaleLineInPlace(prev, prevStart, newStart)
          if (newEnd < newStart + 0.15) newEnd = Number((newStart + 0.15).toFixed(2))
        }
      }
    }
    if (lineIndex + 1 < lines.length && Array.isArray(lines[lineIndex + 1]) && lines[lineIndex + 1].length > 0) {
      const nxt = lines[lineIndex + 1]
      const nxtStart = Number(nxt[0].start ?? 0)
      const nxtEnd = Number(nxt[nxt.length - 1].end ?? 0)
      if (nxtStart < newEnd) {
        const minNxtDur = 0.08 * nxt.length
        if (nxtEnd - newEnd >= minNxtDur) {
          rescaleLineInPlace(nxt, newEnd, nxtEnd)
        } else {
          newEnd = Number(Math.max(newStart + 0.15, nxtEnd - minNxtDur).toFixed(2))
          rescaleLineInPlace(nxt, newEnd, nxtEnd)
        }
      }
    }

    rescaleLineInPlace(line, newStart, newEnd)
    addPendingRealign(lineIndex)
    liveOverlayEnabled.value = true

    currentProject.value.editor_text = rebuildEditorTextFromLines(currentProject.value.lines)
    pushHistory()
  }

  async function regroupLines() {
    if (!currentProject.value) return
    try {
      const res = await fetch('/api/tools/regroup-lines', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          editor_text: currentProject.value.editor_text,
          original_lines: currentProject.value.lines,
        }),
      })
      if (!res.ok) throw new Error('Ошибка склейки строк')
      const data = await res.json()
      currentProject.value.editor_text = data.editor_text
      currentProject.value.lines = data.lines
      pushHistory()
      return data
    } catch (e: any) {
      errorMessage.value = e.message
    }
  }

  async function splitLongLines(maxChars: number = 38, maxWords: number = 8) {
    if (!currentProject.value) return null
    try {
      const res = await fetch('/api/tools/split-lines', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          editor_text: currentProject.value.editor_text,
          original_lines: currentProject.value.lines,
          max_chars: maxChars,
          max_words: maxWords,
        }),
      })
      if (!res.ok) throw new Error('Ошибка разделения строк')
      const data = await res.json()
      currentProject.value.editor_text = data.editor_text
      currentProject.value.lines = data.lines
      pushHistory()
      return data
    } catch (e: any) {
      errorMessage.value = e.message
      throw e
    }
  }

  async function autoDetectFx() {
    if (!currentProject.value) return
    try {
      const res = await fetch('/api/tools/auto-fx', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: currentProject.value.title }),
      })
      if (!res.ok) throw new Error('Ошибка автодетекции припевов')
      const data = await res.json()
      currentProject.value.fx_intervals = data.fx_intervals
      pushHistory()
    } catch (e: any) {
      errorMessage.value = e.message
    }
  }

  async function realignTimings() {
    if (!currentProject.value) return null
    try {
      const res = await fetch('/api/tools/realign-timings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: currentProject.value.title,
          editor_text: currentProject.value.editor_text,
          original_lines: currentProject.value.lines,
        }),
      })
      if (!res.ok) throw new Error('Ошибка перерасчета таймингов')
      const data = await res.json()
      currentProject.value.editor_text = data.editor_text
      currentProject.value.lines = data.lines
      pushHistory()
      return data
    } catch (e: any) {
      errorMessage.value = e.message
      throw e
    }
  }

  async function optimizeTimings(targetScore = 90) {
    if (!currentProject.value) return null
    try {
      const title = encodeURIComponent(currentProject.value.title)
      const res = await fetch(`/api/project/${title}/optimize-timings?target_score=${targetScore}`, {
        method: 'POST',
      })
      if (!res.ok) throw new Error('Ошибка автоподгонки таймингов')
      const data = await res.json()
      currentProject.value.editor_text = data.editor_text
      currentProject.value.lines = data.lines
      if (data.alignment_report) {
        currentProject.value.alignment_report = data.alignment_report
      }
      pushHistory()
      await fetchTimingHistory(currentProject.value.title)
      return data
    } catch (e: any) {
      errorMessage.value = e.message
      throw e
    }
  }

  const timingHistory = ref<TimingSnapshotMeta[]>([])
  const lineMarkByIdx = ref<Record<string, 'good' | 'bad'>>({})
  const diffVsPrevious = ref<Array<LineTimingDiff | null>>([])

  async function fetchTimingHistory(projectTitle?: string) {
    const t = projectTitle || currentProject.value?.title
    if (!t) return
    try {
      const res = await fetch(`/api/project/${encodeURIComponent(t)}/timing-history`)
      if (!res.ok) return
      const data = await res.json()
      timingHistory.value = data.snapshots || []
      lineMarkByIdx.value = data.line_mark_by_idx || {}
      diffVsPrevious.value = data.diff_vs_previous || []
    } catch {
      // ignore non-fatal history load errors
    }
  }

  async function setLineMark(lineIdx: number, mark: 'good' | 'bad' | null) {
    if (!currentProject.value) return
    const title = encodeURIComponent(currentProject.value.title)
    const res = await fetch(`/api/project/${title}/line-mark`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ line_idx: lineIdx, mark }),
    })
    if (!res.ok) throw new Error('Не удалось сохранить отметку строки')
    const data = await res.json()
    lineMarkByIdx.value = data.line_mark_by_idx || {}
  }

  async function restoreTimingSnapshot(snapId: string) {
    if (!currentProject.value) return
    const title = encodeURIComponent(currentProject.value.title)
    const res = await fetch(`/api/project/${title}/timing-history/${encodeURIComponent(snapId)}/restore`, {
      method: 'POST',
    })
    if (!res.ok) throw new Error('Не удалось восстановить версию таймингов')
    const data = await res.json()
    currentProject.value.lines = data.lines
    currentProject.value.editor_text = data.editor_text
    if (data.alignment_report) {
      currentProject.value.alignment_report = data.alignment_report
    }
    pushHistory()
    await fetchTimingHistory(currentProject.value.title)
  }

  async function realignChangedByVocals(lineIndices?: number[]) {
    if (!currentProject.value) return null
    const title = encodeURIComponent(currentProject.value.title)
    const res = await fetch(`/api/project/${title}/realign-changed-by-vocals`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        editor_text: currentProject.value.editor_text,
        lines: currentProject.value.lines,
        line_indices: lineIndices && lineIndices.length ? lineIndices : undefined,
      }),
    })
    if (!res.ok) throw new Error('Ошибка пересчёта изменённых строк по вокалу')
    const data = await res.json()
    if (data.status === 'ok') {
      currentProject.value.lines = data.lines
      currentProject.value.editor_text = data.editor_text
      if (data.alignment_report) {
        currentProject.value.alignment_report = data.alignment_report
      }
      pushHistory()
      await fetchTimingHistory(currentProject.value.title)
      liveOverlayEnabled.value = true
    }
    return data
  }

  async function realignPendingLines() {
    if (!currentProject.value || pendingRealignIndices.value.length === 0) return null
    const target = [...pendingRealignIndices.value]
    const data = await realignChangedByVocals(target)
    if (data?.status === 'ok') {
      const updatedSet = new Set<number>(data.updated_indices || [])
      pendingRealignIndices.value = pendingRealignIndices.value.filter((i) => !updatedSet.has(i))
      liveOverlayEnabled.value = true
    }
    return data
  }

  async function uploadCover(file: File) {
    if (!currentProject.value) return
    errorMessage.value = null
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(currentProject.value.title)}/cover`, {
        method: 'POST',
        body: formData,
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Ошибка загрузки обложки')
      }
      const data = await res.json()
      if (data.cover_image) {
        currentProject.value.cover_image = data.cover_image
      }
      if (data.cover_edge_colors) {
        currentProject.value.cover_edge_colors = data.cover_edge_colors
      }
      coverTimestamp.value = Date.now()
      isDirty.value = true
    } catch (e: any) {
      errorMessage.value = e.message
      throw e
    }
  }

  async function uploadBackground(file: File) {
    if (!currentProject.value) return
    errorMessage.value = null
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(currentProject.value.title)}/background`, {
        method: 'POST',
        body: formData,
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Ошибка загрузки фона')
      }
      const data = await res.json()
      if (data.bg_path) {
        currentProject.value.custom_bg = data.bg_path
      }
      isDirty.value = true
    } catch (e: any) {
      errorMessage.value = e.message
      throw e
    }
  }

  return {
    projects,
    currentProject,
    isLoading,
    isDirty,
    errorMessage,
    coverTimestamp,
    mediaTimestamp,
    hasProject,
    duration,
    title,
    fetchProjects,
    loadProject,
    saveProject,
    uploadCover,
    uploadBackground,
    setVocalIntervals,
    setFxIntervals,
    setEmojiIntervals,
    shiftLineTiming,
    setEditorText,
    regroupLines,
    splitLongLines,
    autoDetectFx,
    realignTimings,
    optimizeTimings,
    timingHistory,
    lineMarkByIdx,
    diffVsPrevious,
    fetchTimingHistory,
    setLineMark,
    restoreTimingSnapshot,
    realignChangedByVocals,
    pendingRealignIndices,
    liveOverlayEnabled,
    addPendingRealign,
    removePendingRealign,
    clearPendingRealign,
    realignPendingLines,
    undo,
    redo,
    canUndo: computed(() => historyIndex.value > 0),
    canRedo: computed(() => historyIndex.value < history.value.length - 1),
  }
})
