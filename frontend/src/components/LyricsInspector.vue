<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useProjectStore } from '@/stores/project'
import { usePipelineStore } from '@/stores/pipeline'
import { usePlayerStore } from '@/stores/player'
import {
  FileText,
  Sparkles,
  Scissors,
  Zap,
  Copy,
  Check,
  Camera,
  Upload,
  Image as ImageIcon,
  RefreshCw,
  Clock,
} from 'lucide-vue-next'

const projectStore = useProjectStore()
const pipelineStore = usePipelineStore()
const playerStore = usePlayerStore()

const showLinesPanel = ref(false)
const showHistoryPanel = ref(false)

const lineRows = computed(() => {
  const lines = projectStore.currentProject?.lines || []
  const marks = projectStore.lineMarkByIdx || {}
  const diffs = projectStore.diffVsPrevious || []
  return lines.map((ln: any[], idx: number) => {
    const start = ln && ln.length ? Number(ln[0].start || 0) : 0
    const end = ln && ln.length ? Number(ln[ln.length - 1].end || 0) : 0
    const text = (ln || []).map((w: any) => w.text).join(' ')
    const diff = diffs[idx] || null
    const mark = marks[String(idx)] || null
    return { idx, start, end, text, diff, mark }
  })
})

const marksSummary = computed(() => {
  const marks = Object.values(projectStore.lineMarkByIdx || {})
  return {
    good: marks.filter((m) => m === 'good').length,
    bad: marks.filter((m) => m === 'bad').length,
  }
})

const pendingRealignRows = computed(() => {
  const lines = projectStore.currentProject?.lines || []
  return projectStore.pendingRealignIndices
    .filter((idx) => idx >= 0 && idx < lines.length && Array.isArray(lines[idx]) && lines[idx].length > 0)
    .map((idx) => {
      const ln = lines[idx]
      const start = Number(ln[0].start || 0)
      const end = Number(ln[ln.length - 1].end || 0)
      const text = ln.map((w: any) => w.text).join(' ')
      return { idx, start, end, dur: Math.max(0, end - start), text }
    })
})

function togglePendingRealign(idx: number) {
  if (projectStore.pendingRealignIndices.includes(idx)) {
    projectStore.removePendingRealign(idx)
  } else {
    projectStore.addPendingRealign(idx)
  }
}

async function handleRealignPendingQueue() {
  if (isProcessingTool.value || pendingRealignRows.value.length === 0) return
  isProcessingTool.value = true
  try {
    const data = await projectStore.realignPendingLines()
    if (data?.status === 'noop') {
      showToolNotice('Нет строк для пересчёта')
    } else if (data?.updated_indices) {
      showToolNotice(`🎙️ Пересчитано по вокалу: ${data.updated_indices.length} строк`)
    }
  } finally {
    isProcessingTool.value = false
  }
}

function formatShortTime(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function formatShift(sec: number): string {
  const sign = sec > 0 ? '+' : ''
  return `${sign}${sec.toFixed(2)}s`
}

async function toggleLineMark(idx: number, target: 'good' | 'bad') {
  const current = projectStore.lineMarkByIdx[String(idx)]
  const next = current === target ? null : target
  await projectStore.setLineMark(idx, next)
}

async function handleRestoreSnapshot(snapId: string) {
  if (isProcessingTool.value) return
  isProcessingTool.value = true
  try {
    await projectStore.restoreTimingSnapshot(snapId)
    showToolNotice('🕘 Версия таймингов восстановлена')
  } finally {
    isProcessingTool.value = false
  }
}

async function handleRealignChangedByVocals(lineIndices?: number[]) {
  if (isProcessingTool.value) return
  isProcessingTool.value = true
  try {
    const data = await projectStore.realignChangedByVocals(lineIndices)
    if (data?.status === 'noop') {
      showToolNotice('Нет изменённых или 👎 строк для пересчёта')
    } else if (data?.updated_indices) {
      showToolNotice(`🎙️ Пересчитано по вокалу: ${data.updated_indices.length} строк`)
    }
  } finally {
    isProcessingTool.value = false
  }
}

const localText = ref('')
const isCopied = ref(false)
const isDraggingCover = ref(false)
const coverLoadError = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const uploadStatus = ref('')

const coverUrl = computed(() => {
  if (!projectStore.currentProject?.title) return ''
  return `/api/media/${encodeURIComponent(projectStore.currentProject.title)}/cover?t=${projectStore.coverTimestamp}`
})

watch(
  () => projectStore.currentProject?.title,
  () => {
    coverLoadError.value = false
    uploadStatus.value = ''
  }
)

watch(
  () => projectStore.currentProject?.editor_text,
  (val) => {
    localText.value = val || ''
  },
  { immediate: true }
)

function onTextChange() {
  projectStore.setEditorText(localText.value)
}

function copyToClipboard() {
  if (!localText.value) return
  navigator.clipboard.writeText(localText.value)
  isCopied.value = true
  setTimeout(() => {
    isCopied.value = false
  }, 2000)
}

async function handleCoverFile(file: File) {
  if (!file) return
  try {
    uploadStatus.value = 'Загрузка...'
    await projectStore.uploadCover(file)
    coverLoadError.value = false
    uploadStatus.value = 'Обложка обновлена! Нажмите «Пересобрать MP4»'
    setTimeout(() => {
      uploadStatus.value = ''
    }, 4000)
  } catch (err: any) {
    uploadStatus.value = err.message || 'Ошибка загрузки'
  }
}

function onCoverSelect(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    handleCoverFile(target.files[0])
  }
}

function onCoverDrop(e: DragEvent) {
  isDraggingCover.value = false
  if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
    handleCoverFile(e.dataTransfer.files[0])
  }
}

const isProcessingTool = ref(false)
const toolNotice = ref('')

function showToolNotice(msg: string) {
  toolNotice.value = msg
  setTimeout(() => {
    toolNotice.value = ''
  }, 3500)
}

async function handleRegroupLines() {
  if (isProcessingTool.value) return
  isProcessingTool.value = true
  try {
    const data = await projectStore.regroupLines()
    if (data) {
      showToolNotice(`✨ Строки объединены (${data.original_count} ➔ ${data.new_count})`)
    }
  } finally {
    isProcessingTool.value = false
  }
}

async function handleSplitLongLines() {
  if (isProcessingTool.value) return
  isProcessingTool.value = true
  try {
    const data = await projectStore.splitLongLines()
    if (data) {
      if (data.split_count > 0) {
        showToolNotice(`✂️ Разделено: +${data.split_count} (всего ${data.new_count} строк)`)
      } else {
        showToolNotice('✂️ Длинных строк не обнаружено')
      }
    }
  } finally {
    isProcessingTool.value = false
  }
}

async function handleAutoDetectFx() {
  if (isProcessingTool.value) return
  isProcessingTool.value = true
  try {
    await projectStore.autoDetectFx()
    const count = projectStore.currentProject?.fx_intervals?.length || 0
    showToolNotice(`⚡ Обнаружено ${count} зон спецэффектов`)
  } finally {
    isProcessingTool.value = false
  }
}

async function handleRealignTimings() {
  if (isProcessingTool.value) return
  isProcessingTool.value = true
  try {
    const data = await projectStore.realignTimings()
    if (data) {
      showToolNotice(`⏱️ Тайминги пересчитаны (${data.count} строк)`)
    }
  } finally {
    isProcessingTool.value = false
  }
}

async function handleOptimizeTimings() {
  if (isProcessingTool.value) return
  isProcessingTool.value = true
  try {
    const data = await projectStore.optimizeTimings(90)
    if (data) {
      const score = data.alignment_report?.overall_score
      showToolNotice(
        score !== undefined
          ? `🎯 Точность таймингов: ${Number(score).toFixed(1)}%`
          : '🎯 Автоподгонка таймингов завершена',
      )
    }
  } finally {
    isProcessingTool.value = false
  }
}
</script>

<template>
  <aside class="w-full h-full bg-studio-panel flex flex-col shrink-0 select-none">
    <!-- Header -->
    <div class="h-10 px-3 border-b border-studio-border flex items-center justify-between text-xs font-semibold text-slate-300">
      <div class="flex items-center space-x-1.5">
        <FileText class="w-4 h-4 text-sky-400" />
        <span>Текст и тайминги</span>
      </div>

      <div class="flex items-center space-x-1.5">
        <button
          @click="pipelineStore.quickRebuild()"
          :disabled="!projectStore.hasProject || pipelineStore.isRebuilding"
          class="flex items-center space-x-1 px-2 py-1 rounded bg-sky-600 hover:bg-sky-500 text-white text-[11px] font-semibold shadow-sm disabled:opacity-40 transition-colors"
          title="Быстро пересобрать видео с отредактированным текстом и таймингами"
        >
          <RefreshCw :class="['w-3 h-3', pipelineStore.isRebuilding ? 'animate-spin' : '']" />
          <span>Пересобрать видео</span>
        </button>

        <button
          @click="copyToClipboard"
          title="Скопировать в буфер"
          class="p-1 rounded text-studio-muted hover:text-white hover:bg-studio-surface transition-colors"
        >
          <Check v-if="isCopied" class="w-3.5 h-3.5 text-emerald-400" />
          <Copy v-else class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- Scrollable Inspector Body -->
    <div class="flex-1 overflow-y-auto min-h-0 flex flex-col">
    <!-- Cover Art Card / Quick Uploader -->
    <div
      v-if="projectStore.hasProject"
      class="p-2.5 bg-studio-surface/40 border-b border-studio-border flex flex-col space-y-1.5 shrink-0"
    >
      <div class="flex items-center space-x-3">
        <!-- Cover Thumbnail with Drag & Drop -->
        <div
          class="relative w-16 h-16 rounded-lg overflow-hidden border border-studio-border/80 group cursor-pointer shrink-0 bg-black shadow-md"
          @click="fileInputRef?.click()"
          @dragover.prevent="isDraggingCover = true"
          @dragleave.prevent="isDraggingCover = false"
          @drop.prevent="onCoverDrop"
          title="Нажмите или перетащите картинку для смены обложки"
        >
          <img
            :src="coverUrl"
            @error="coverLoadError = true"
            v-if="!coverLoadError"
            class="w-full h-full object-cover"
          />
          <div v-else class="w-full h-full flex items-center justify-center bg-slate-800 text-slate-500">
            <ImageIcon class="w-6 h-6" />
          </div>

          <!-- Hover / Drag Overlay -->
          <div
            :class="[
              'absolute inset-0 bg-black/65 flex flex-col items-center justify-center text-white transition-opacity',
              isDraggingCover ? 'opacity-100 bg-sky-600/70' : 'opacity-0 group-hover:opacity-100'
            ]"
          >
            <Camera class="w-5 h-5 mb-0.5 text-sky-400" />
            <span class="text-[9px] font-medium leading-tight">Сменить</span>
          </div>
        </div>

        <input
          ref="fileInputRef"
          type="file"
          accept="image/*"
          class="hidden"
          @change="onCoverSelect"
        />

        <div class="flex-1 min-w-0">
          <div class="text-xs font-semibold text-white truncate" :title="projectStore.title">
            {{ projectStore.title }}
          </div>
          <p class="text-[11px] text-studio-muted mt-0.5">
            Обложка трека (Ambilight)
          </p>
          <button
            @click="fileInputRef?.click()"
            class="mt-1 text-[11px] text-sky-400 hover:text-sky-300 font-medium flex items-center space-x-1"
          >
            <Upload class="w-3 h-3" />
            <span>Прикрепить картинку</span>
          </button>
        </div>
      </div>

      <!-- Upload status message -->
      <div v-if="uploadStatus" class="text-[11px] font-medium text-emerald-400 bg-emerald-500/10 px-2 py-1 rounded border border-emerald-500/20">
        {{ uploadStatus }}
      </div>
    </div>

    <!-- Quick Tools -->
    <div class="p-2.5 bg-studio-surface/50 border-b border-studio-border flex flex-col space-y-1.5 shrink-0">
      <div v-if="toolNotice" class="text-[11px] font-medium text-sky-400 bg-sky-500/10 px-2 py-1 rounded border border-sky-500/20 text-center transition-all">
        {{ toolNotice }}
      </div>

      <!-- Main Quick Rebuild Video Button in tools panel -->
      <button
        @click="pipelineStore.quickRebuild()"
        :disabled="!projectStore.hasProject || pipelineStore.isRebuilding"
        class="w-full flex items-center justify-center space-x-1.5 py-1.5 px-2 rounded text-xs font-semibold bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 text-white shadow-sm border border-sky-400/30 disabled:opacity-40 transition-all"
        title="Пересобрать видео со всеми новыми правками текста, таймингов и эффектов"
      >
        <RefreshCw :class="['w-3.5 h-3.5', pipelineStore.isRebuilding ? 'animate-spin' : '']" />
        <span>Пересобрать видео с текстом</span>
      </button>

      <!-- Pending Realign Queue from Timeline edits -->
      <div
        v-if="projectStore.hasProject && pendingRealignRows.length > 0"
        class="p-2 rounded bg-amber-500/10 border border-amber-400/40 flex flex-col space-y-1.5"
      >
        <div class="flex items-center justify-between text-[11px] font-semibold text-amber-300">
          <span>🎙️ На пересчёт с таймлайна: {{ pendingRealignRows.length }}</span>
          <button
            @click="projectStore.clearPendingRealign()"
            class="text-[10px] font-normal text-slate-400 hover:text-rose-300"
          >
            Очистить
          </button>
        </div>
        <div class="max-h-32 overflow-y-auto divide-y divide-amber-500/15">
          <div
            v-for="row in pendingRealignRows"
            :key="row.idx"
            class="py-1 flex items-center gap-1.5 text-[11px]"
          >
            <button
              @click="playerStore.seek(row.start)"
              class="font-mono text-sky-300 shrink-0 hover:underline"
              :title="`Перемотать на ${row.start.toFixed(2)}с`"
            >
              {{ formatShortTime(row.start) }}
            </button>
            <span class="font-mono text-[10px] text-amber-300/80 shrink-0">{{ row.dur.toFixed(1) }}s</span>
            <span class="truncate flex-1 text-slate-200 cursor-pointer" @click="playerStore.seek(row.start)" :title="row.text">
              {{ row.text }}
            </span>
            <button
              @click="projectStore.removePendingRealign(row.idx)"
              class="px-1 text-slate-400 hover:text-rose-400 font-bold"
              title="Убрать эту строку из очереди на пересчёт"
            >✕</button>
          </div>
        </div>
        <button
          @click="handleRealignPendingQueue"
          :disabled="isProcessingTool"
          class="w-full py-1 px-2 rounded text-xs font-semibold bg-amber-500 hover:bg-amber-400 text-slate-950 transition-colors disabled:opacity-40"
        >
          Пересчитать выбранные ({{ pendingRealignRows.length }})
        </button>
      </div>

      <button
        @click="handleRealignChangedByVocals()"
        :disabled="!projectStore.hasProject || isProcessingTool"
        class="w-full flex items-center justify-center space-x-1.5 py-1.5 px-2 rounded text-xs font-medium bg-studio-surface hover:bg-slate-700 text-cyan-300 border border-studio-border disabled:opacity-40 transition-colors"
        title="Перепрогнать через распознавание вокала (MMS_FA) только изменённые или 👎 строки внутри их границ"
      >
        <span>🎙️</span>
        <span>Пересчитать изменённые по вокалу</span>
      </button>

      <div class="grid grid-cols-2 gap-1.5">
        <button
          @click="handleRealignTimings"
          :disabled="!projectStore.hasProject || isProcessingTool"
          class="flex items-center justify-center space-x-1 py-1.5 px-2 rounded text-[11px] font-medium bg-studio-surface hover:bg-slate-700 text-emerald-300 border border-studio-border disabled:opacity-40 transition-colors"
          title="Полный сброс: заново выровнять все строки текста по распознанным словам (сбросит ручные сдвиги)"
        >
          <Clock :class="['w-3 h-3 text-emerald-400 shrink-0', isProcessingTool ? 'animate-spin' : '']" />
          <span class="truncate">Сбросить всё</span>
        </button>

        <button
          @click="handleOptimizeTimings"
          :disabled="!projectStore.hasProject || isProcessingTool"
          class="flex items-center justify-center space-x-1 py-1.5 px-2 rounded text-[11px] font-medium bg-studio-surface hover:bg-slate-700 text-amber-300 border border-studio-border disabled:opacity-40 transition-colors"
          title="Подогнать тайминги строк по вокалу (Whisper+RMS vs CTC) до 90%+"
        >
          <span>🎯</span>
          <span class="truncate">Авто 90%+</span>
        </button>
      </div>

      <div
        v-if="projectStore.currentProject?.alignment_report"
        class="px-2 py-1.5 rounded bg-studio-surface/70 border border-studio-border text-[11px] text-slate-300 leading-snug"
      >
        <div class="font-medium text-amber-300 flex items-center justify-between">
          <span>Акустическая проверка (ориентир): {{ projectStore.currentProject.alignment_report.overall_score.toFixed(1) }}%</span>
          <span v-if="marksSummary.good || marksSummary.bad" class="text-[10px] text-slate-300">
            👍{{ marksSummary.good }} 👎{{ marksSummary.bad }}
          </span>
        </div>
        <div class="text-slate-400 mt-0.5">
          вступления {{ Math.round(projectStore.currentProject.alignment_report.onset_score) }}% ·
          покрытие {{ Math.round(projectStore.currentProject.alignment_report.coverage_score) }}% ·
          темп {{ Math.round(projectStore.currentProject.alignment_report.tempo_score) }}%
        </div>
      </div>

      <!-- Collapsible Line Marks & Diffs -->
      <div v-if="projectStore.hasProject" class="border border-studio-border rounded bg-studio-surface/40">
        <button
          @click="showLinesPanel = !showLinesPanel"
          class="w-full px-2 py-1 text-[11px] font-medium text-slate-200 flex items-center justify-between hover:bg-slate-700/40"
        >
          <span>Строки (👍 {{ marksSummary.good }} / 👎 {{ marksSummary.bad }})</span>
          <span class="text-slate-400">{{ showLinesPanel ? '▲' : '▼' }}</span>
        </button>
        <div v-if="showLinesPanel" class="max-h-44 overflow-y-auto border-t border-studio-border divide-y divide-studio-border/50">
          <div
            v-for="row in lineRows"
            :key="row.idx"
            class="px-2 py-1 text-[11px] flex items-center gap-1.5 hover:bg-slate-700/30"
          >
            <button
              @click="playerStore.seek(row.start)"
              class="text-sky-400 font-mono shrink-0 hover:underline"
              :title="`Перемотать на ${row.start.toFixed(2)}с`"
            >
              {{ formatShortTime(row.start) }}
            </button>
            <span v-if="row.mark === 'good'" title="Зафиксировано (👍)">🔒</span>
            <span class="truncate flex-1 text-slate-200 cursor-pointer" @click="playerStore.seek(row.start)" :title="row.text">
              {{ row.text }}
            </span>
            <span
              v-if="row.diff && Math.abs(row.diff.start_shift) >= 0.05"
              :class="['font-mono text-[10px] shrink-0', row.diff.start_shift > 0 ? 'text-amber-400' : 'text-emerald-400']"
              title="Сдвиг начала относительно предыдущей версии"
            >
              {{ formatShift(row.diff.start_shift) }}
            </span>
            <button
              @click="togglePendingRealign(row.idx)"
              :class="[
                'px-1 rounded text-[10px] font-mono',
                projectStore.pendingRealignIndices.includes(row.idx)
                  ? 'bg-amber-500/30 text-amber-200'
                  : 'text-slate-400 hover:text-amber-300'
              ]"
              title="Добавить или убрать строку из очереди пересчёта"
            >{{ projectStore.pendingRealignIndices.includes(row.idx) ? '✓🎙️' : '+🎙️' }}</button>
            <button
              @click="handleRealignChangedByVocals([row.idx])"
              :disabled="isProcessingTool"
              class="px-1 rounded text-[11px] text-slate-400 hover:text-cyan-300"
              title="Пересчитать слова этой строки по вокалу прямо сейчас"
            >🎙️</button>
            <button
              @click="toggleLineMark(row.idx, 'good')"
              :class="['px-1 rounded text-[11px]', row.mark === 'good' ? 'bg-emerald-600/40 text-emerald-200' : 'text-slate-400 hover:text-emerald-300']"
              title="Хорошо (зафиксировать при перегенерации)"
            >👍</button>
            <button
              @click="toggleLineMark(row.idx, 'bad')"
              :class="['px-1 rounded text-[11px]', row.mark === 'bad' ? 'bg-rose-600/40 text-rose-200' : 'text-slate-400 hover:text-rose-300']"
              title="Плохо (попробовать другой вариант при перегенерации)"
            >👎</button>
          </div>
        </div>
      </div>

      <!-- Collapsible Timing History -->
      <div v-if="projectStore.hasProject" class="border border-studio-border rounded bg-studio-surface/40">
        <button
          @click="showHistoryPanel = !showHistoryPanel"
          class="w-full px-2 py-1 text-[11px] font-medium text-slate-200 flex items-center justify-between hover:bg-slate-700/40"
        >
          <span>🕘 История таймингов ({{ projectStore.timingHistory.length }})</span>
          <span class="text-slate-400">{{ showHistoryPanel ? '▲' : '▼' }}</span>
        </button>
        <div v-if="showHistoryPanel" class="max-h-36 overflow-y-auto border-t border-studio-border divide-y divide-studio-border/50">
          <div v-if="projectStore.timingHistory.length === 0" class="px-2 py-1.5 text-[11px] text-slate-400">
            Снимков пока нет — появятся после перегенерации или автоподгонки.
          </div>
          <div
            v-for="snap in projectStore.timingHistory"
            :key="snap.id"
            class="px-2 py-1 text-[11px] flex items-center justify-between gap-1.5"
          >
            <div class="truncate text-slate-300">
              <span class="font-mono text-slate-400">{{ snap.created_at?.slice(11, 16) }}</span>
              · {{ snap.reason_label }}
              <span class="text-slate-400">· 👍{{ snap.marks_summary?.good || 0 }} 👎{{ snap.marks_summary?.bad || 0 }}</span>
            </div>
            <button
              @click="handleRestoreSnapshot(snap.id)"
              :disabled="isProcessingTool"
              class="px-1.5 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-[10px] text-sky-300 shrink-0"
            >
              Восстановить
            </button>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-1.5">
        <button
          @click="handleRegroupLines"
          :disabled="!projectStore.hasProject || isProcessingTool"
          class="flex items-center justify-center space-x-1 py-1.5 px-2 rounded text-[11px] font-medium bg-studio-surface hover:bg-slate-700 text-sky-300 border border-studio-border disabled:opacity-40 transition-colors"
        >
          <Sparkles class="w-3 h-3 text-sky-400 shrink-0" />
          <span class="truncate">Склеить</span>
        </button>

        <button
          @click="handleSplitLongLines"
          :disabled="!projectStore.hasProject || isProcessingTool"
          class="flex items-center justify-center space-x-1 py-1.5 px-2 rounded text-[11px] font-medium bg-studio-surface hover:bg-slate-700 text-amber-300 border border-studio-border disabled:opacity-40 transition-colors"
        >
          <Scissors class="w-3 h-3 text-amber-400 shrink-0" />
          <span class="truncate">Разделить</span>
        </button>
      </div>

      <button
        @click="handleAutoDetectFx"
        :disabled="!projectStore.hasProject || isProcessingTool"
        class="w-full flex items-center justify-center space-x-1.5 py-1.5 px-2 rounded text-xs font-medium bg-studio-surface hover:bg-slate-700 text-purple-300 border border-studio-border disabled:opacity-40 transition-colors"
      >
        <Zap class="w-3.5 h-3.5 text-purple-400" />
        <span>Автодетекция припевов</span>
      </button>
    </div>

    <!-- Editor Textarea -->
    <div class="flex-1 p-2 flex flex-col min-h-[220px] shrink-0">
      <textarea
        v-model="localText"
        @input="onTextChange"
        placeholder="Текст караоке с таймингами..."
        class="flex-1 w-full min-h-[190px] bg-studio-bg border border-studio-border/70 rounded p-2 text-xs font-mono text-slate-200 resize-y focus:outline-none focus:border-sky-500 leading-relaxed"
      ></textarea>
      <div class="text-[10px] text-studio-muted mt-1 px-1 flex justify-between">
        <span>Формат: [00:12.30 -> 00:16.80] Текст</span>
        <span>{{ projectStore.currentProject?.lines?.length || 0 }} строк</span>
      </div>
    </div>
    </div>
  </aside>
</template>
