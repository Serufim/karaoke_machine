<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useProjectStore } from '@/stores/project'
import { usePipelineStore } from '@/stores/pipeline'
import { usePlayerStore } from '@/stores/player'
import {
  Wand2,
  X,
  Play,
  RotateCcw,
  Check,
  Film,
  Sparkles,
  Clock,
  Sliders,
  Plus,
  Minus,
  Loader2,
} from 'lucide-vue-next'

const props = defineProps<{
  initialStart: number
  initialEnd: number
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'applied'): void
}>()

const projectStore = useProjectStore()
const pipelineStore = usePipelineStore()
const playerStore = usePlayerStore()

const sliceStart = ref<number>(Math.max(0, Number(props.initialStart.toFixed(2))))
const sliceEnd = ref<number>(Math.max(sliceStart.value + 0.5, Number(props.initialEnd.toFixed(2))))
const sliceText = ref<string>('')
const alignMode = ref<'whisper' | 'syllables_rms'>('whisper')

const isCalibrating = ref<boolean>(false)
const isPreviewing = ref<boolean>(false)
const isApplying = ref<boolean>(false)
const autoRebuild = ref<boolean>(false)

interface CalibratedWord {
  text: string
  start: number
  end: number
  syllables?: number
}

const calibratedWords = ref<CalibratedWord[]>([])
const previewUrl = ref<string | null>(null)
const previewVideoRef = ref<HTMLVideoElement | null>(null)
const isPreviewPlaying = ref<boolean>(false)

const duration = computed(() => Math.max(0.1, Number((sliceEnd.value - sliceStart.value).toFixed(2))))

function formatSec(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  const cs = Math.floor((sec % 1) * 100)
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}.${cs.toString().padStart(2, '0')}`
}

onMounted(() => {
  // Extract any existing lyrics that overlap this slice
  const lines = projectStore.currentProject?.lines || []
  const foundWords: CalibratedWord[] = []
  for (const line of lines) {
    if (Array.isArray(line)) {
      for (const w of line) {
        const s = Number(w.start ?? 0)
        const e = Number(w.end ?? s + 0.1)
        if (e > sliceStart.value && s < sliceEnd.value) {
          foundWords.push({
            text: String(w.text ?? ''),
            start: s,
            end: e,
            syllables: Number(w.syllables ?? 1),
          })
        }
      }
    }
  }

  if (foundWords.length > 0) {
    calibratedWords.value = foundWords
    sliceText.value = foundWords.map((w) => w.text).join(' ')
  }
})

function nudgeStart(delta: number) {
  sliceStart.value = Math.max(0, Number((sliceStart.value + delta).toFixed(2)))
  if (sliceEnd.value <= sliceStart.value + 0.2) {
    sliceEnd.value = Number((sliceStart.value + 0.5).toFixed(2))
  }
}

function nudgeEnd(delta: number) {
  sliceEnd.value = Math.max(sliceStart.value + 0.2, Number((sliceEnd.value + delta).toFixed(2)))
}

function nudgeWord(wordIdx: number, field: 'start' | 'end', delta: number) {
  const w = calibratedWords.value[wordIdx]
  if (!w) return
  const newVal = Number((w[field] + delta).toFixed(2))
  if (field === 'start') {
    w.start = Math.max(0, newVal)
    if (w.end <= w.start) w.end = Number((w.start + 0.1).toFixed(2))
  } else {
    w.end = Math.max(w.start + 0.05, newVal)
  }
}

async function onCalibrate() {
  if (!projectStore.currentProject) return
  if (!sliceText.value.trim()) {
    alert('Пожалуйста, введите слова для этого участка.')
    return
  }

  isCalibrating.value = true
  try {
    const res = await fetch('/api/tools/slice-align', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: projectStore.currentProject.title,
        start: sliceStart.value,
        end: sliceEnd.value,
        text: sliceText.value.trim(),
        mode: alignMode.value,
      }),
    })
    const data = await res.json()
    if (!res.ok) {
      throw new Error(data.detail || 'Ошибка калибровки')
    }
    calibratedWords.value = data.words || []
  } catch (err: any) {
    alert(`Ошибка: ${err.message}`)
  } finally {
    isCalibrating.value = false
  }
}

async function onGeneratePreview() {
  if (!projectStore.currentProject) return
  if (calibratedWords.value.length === 0) {
    alert('Сначала откалибруйте тайминги или добавьте слова.')
    return
  }

  isPreviewing.value = true
  try {
    const res = await fetch('/api/tools/slice-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: projectStore.currentProject.title,
        start: sliceStart.value,
        end: sliceEnd.value,
        words: calibratedWords.value,
      }),
    })
    const data = await res.json()
    if (!res.ok) {
      throw new Error(data.detail || 'Ошибка сборки превью')
    }
    previewUrl.value = data.preview_url
  } catch (err: any) {
    alert(`Ошибка превью: ${err.message}`)
  } finally {
    isPreviewing.value = false
  }
}

function playWordSnippet(w: CalibratedWord) {
  playerStore.seek(w.start)
  playerStore.play()
}

async function onApplyToProject() {
  if (!projectStore.currentProject) return
  if (calibratedWords.value.length === 0) {
    alert('Нет откалиброванных слов для сохранения.')
    return
  }

  isApplying.value = true
  try {
    const res = await fetch('/api/tools/slice-apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: projectStore.currentProject.title,
        start: sliceStart.value,
        end: sliceEnd.value,
        words: calibratedWords.value,
      }),
    })
    const data = await res.json()
    if (!res.ok) {
      throw new Error(data.detail || 'Ошибка сохранения')
    }

    // Synchronize into local Pinia state
    projectStore.currentProject.lines = data.lines
    projectStore.currentProject.editor_text = data.editor_text

    if (autoRebuild.value) {
      pipelineStore.startRebuild(projectStore.currentProject.title)
    }

    emit('applied')
    emit('close')
  } catch (err: any) {
    alert(`Ошибка сохранения: ${err.message}`)
  } finally {
    isApplying.value = false
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 select-none">
    <div class="w-full max-w-3xl bg-studio-panel border border-studio-border rounded-xl shadow-2xl flex flex-col overflow-hidden max-h-[92vh]">
      <!-- Header -->
      <div class="px-5 py-3.5 border-b border-studio-border flex items-center justify-between bg-studio-surface/60">
        <div class="flex items-center space-x-2.5">
          <div class="w-8 h-8 rounded-lg bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
            <Wand2 class="w-4 h-4" />
          </div>
          <div>
            <h2 class="text-sm font-semibold text-white flex items-center space-x-2">
              <span>Мануальный режим: точечное выравнивание участка</span>
            </h2>
            <p class="text-[11px] text-studio-muted">
              Укажите текст участка вокала, запустите нейрокалибровку и посмотрите тестовый кусок видео перед сохранением
            </p>
          </div>
        </div>
        <button @click="emit('close')" class="text-studio-muted hover:text-white transition-colors">
          <X class="w-5 h-5" />
        </button>
      </div>

      <!-- Scrollable Body -->
      <div class="p-5 space-y-4 overflow-y-auto text-xs">
        <!-- Interval & Method Bar -->
        <div class="bg-studio-surface border border-studio-border rounded-xl p-3.5 flex flex-wrap items-center justify-between gap-3">
          <!-- Time Interval -->
          <div class="flex items-center space-x-3">
            <div class="flex items-center space-x-1.5">
              <Clock class="w-4 h-4 text-sky-400 shrink-0" />
              <span class="text-slate-300 font-medium">Интервал:</span>
            </div>

            <!-- Start -->
            <div class="flex items-center space-x-1 bg-studio-panel border border-studio-border rounded-lg px-2 py-1">
              <span class="text-studio-muted text-[10px]">От:</span>
              <span class="font-mono text-emerald-400 font-semibold">{{ formatSec(sliceStart) }}</span>
              <div class="flex flex-col ml-1">
                <button type="button" @click="nudgeStart(0.2)" class="text-slate-400 hover:text-white leading-none text-[9px]">+</button>
                <button type="button" @click="nudgeStart(-0.2)" class="text-slate-400 hover:text-white leading-none text-[9px]">-</button>
              </div>
            </div>

            <span class="text-studio-muted">→</span>

            <!-- End -->
            <div class="flex items-center space-x-1 bg-studio-panel border border-studio-border rounded-lg px-2 py-1">
              <span class="text-studio-muted text-[10px]">До:</span>
              <span class="font-mono text-amber-400 font-semibold">{{ formatSec(sliceEnd) }}</span>
              <div class="flex flex-col ml-1">
                <button type="button" @click="nudgeEnd(0.2)" class="text-slate-400 hover:text-white leading-none text-[9px]">+</button>
                <button type="button" @click="nudgeEnd(-0.2)" class="text-slate-400 hover:text-white leading-none text-[9px]">-</button>
              </div>
            </div>

            <span class="text-studio-muted text-[11px]">({{ duration }} с)</span>
          </div>

          <!-- Alignment Engine Mode -->
          <div class="flex items-center space-x-2">
            <label class="text-slate-300 font-medium flex items-center space-x-1">
              <Sliders class="w-3.5 h-3.5 text-sky-400" />
              <span>Метод:</span>
            </label>
            <select
              v-model="alignMode"
              class="bg-studio-panel border border-studio-border rounded-lg px-2.5 py-1 text-white focus:outline-none focus:border-sky-500 font-medium text-xs"
            >
              <option value="whisper">Whisper нейросеть (по звуку)</option>
              <option value="syllables_rms">Слоги + RMS энергии вокала</option>
            </select>
          </div>
        </div>

        <!-- Target Textarea + Calibrate Action -->
        <div class="space-y-2">
          <label class="font-medium text-slate-300 flex justify-between items-center">
            <span>Текст этого участка (слова песни):</span>
            <span class="text-studio-muted text-[10px]">Точно укажите слова, которые звучат в этом фрагменте</span>
          </label>
          <div class="relative">
            <textarea
              v-model="sliceText"
              rows="2"
              placeholder="Введите слова, которые поются на этом отрезке времени..."
              class="w-full bg-studio-surface border border-studio-border rounded-lg p-3 text-sm text-white focus:outline-none focus:border-sky-500 font-mono leading-relaxed resize-none"
            ></textarea>
          </div>

          <div class="flex justify-end">
            <button
              type="button"
              @click="onCalibrate"
              :disabled="isCalibrating || !sliceText.trim()"
              class="flex items-center space-x-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs shadow-md transition-colors disabled:opacity-40"
            >
              <Loader2 v-if="isCalibrating" class="w-4 h-4 animate-spin" />
              <Sparkles v-else class="w-4 h-4" />
              <span>{{ isCalibrating ? 'Нейрокалибровка таймингов...' : 'Откалибровать тайминги слов' }}</span>
            </button>
          </div>
        </div>

        <!-- Calibrated Words List / Interactive Timing Adjuster -->
        <div v-if="calibratedWords.length > 0" class="space-y-2 pt-2 border-t border-studio-border">
          <div class="flex items-center justify-between">
            <label class="font-medium text-slate-300 flex items-center space-x-1.5">
              <span>Слова и точные тайминги ({{ calibratedWords.length }} шт):</span>
              <span class="text-[10px] text-studio-muted font-normal">кликните на стрелки для микро-подстройки</span>
            </label>
            <button
              type="button"
              @click="onGeneratePreview"
              :disabled="isPreviewing"
              class="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-semibold text-xs shadow-md transition-colors disabled:opacity-40"
            >
              <Loader2 v-if="isPreviewing" class="w-3.5 h-3.5 animate-spin" />
              <Film v-else class="w-3.5 h-3.5" />
              <span>{{ isPreviewing ? 'Рендеринг клипа...' : 'Собрать превью куска видео' }}</span>
            </button>
          </div>

          <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2 max-h-48 overflow-y-auto p-1 bg-studio-surface/40 rounded-xl border border-studio-border">
            <div
              v-for="(w, idx) in calibratedWords"
              :key="idx"
              class="bg-studio-surface border border-studio-border rounded-lg p-2.5 flex flex-col justify-between space-y-2 shadow-sm hover:border-sky-500/50 transition-colors"
            >
              <div class="flex items-center justify-between">
                <input
                  v-model="w.text"
                  type="text"
                  class="font-semibold text-white bg-transparent border-b border-transparent hover:border-studio-border focus:border-sky-500 focus:outline-none w-24 text-xs"
                />
                <button
                  type="button"
                  @click="playWordSnippet(w)"
                  title="Прослушать слово в аудио"
                  class="text-studio-muted hover:text-sky-400 transition-colors p-1"
                >
                  <Play class="w-3.5 h-3.5" />
                </button>
              </div>

              <div class="flex items-center justify-between text-[11px] font-mono text-studio-muted">
                <div class="flex items-center space-x-1">
                  <span>{{ w.start.toFixed(2) }}</span>
                  <div class="flex space-x-0.5">
                    <button @click="nudgeWord(idx, 'start', -0.05)" class="hover:text-white px-0.5 text-[10px]">-</button>
                    <button @click="nudgeWord(idx, 'start', 0.05)" class="hover:text-white px-0.5 text-[10px]">+</button>
                  </div>
                </div>
                <span>→</span>
                <div class="flex items-center space-x-1">
                  <span>{{ w.end.toFixed(2) }}</span>
                  <div class="flex space-x-0.5">
                    <button @click="nudgeWord(idx, 'end', -0.05)" class="hover:text-white px-0.5 text-[10px]">-</button>
                    <button @click="nudgeWord(idx, 'end', 0.05)" class="hover:text-white px-0.5 text-[10px]">+</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Video Slice Preview Player -->
        <div v-if="previewUrl" class="space-y-2 pt-2 border-t border-studio-border">
          <div class="flex items-center justify-between">
            <label class="font-medium text-slate-300 flex items-center space-x-1.5">
              <Film class="w-4 h-4 text-sky-400" />
              <span>Тестовое превью видеокараоке (Full HD):</span>
            </label>
            <span class="text-[10px] text-emerald-400 font-medium">Видео готово к просмотру</span>
          </div>

          <div class="w-full bg-black rounded-xl overflow-hidden border border-studio-border aspect-video shadow-2xl relative flex items-center justify-center">
            <video
              ref="previewVideoRef"
              :src="previewUrl"
              controls
              autoplay
              loop
              class="w-full h-full object-contain"
            ></video>
          </div>
        </div>
      </div>

      <!-- Footer Actions -->
      <div class="px-5 py-3 border-t border-studio-border bg-studio-surface/80 flex items-center justify-between">
        <label class="flex items-center space-x-2 cursor-pointer text-xs">
          <input type="checkbox" v-model="autoRebuild" class="rounded bg-studio-surface border-studio-border text-sky-500" />
          <span class="text-slate-300">Сразу запустить пересборку видеокараоке</span>
        </label>

        <div class="flex items-center space-x-3">
          <button
            type="button"
            @click="emit('close')"
            class="px-4 py-2 text-xs font-medium rounded-lg text-slate-300 hover:text-white hover:bg-studio-surface transition-colors"
          >
            Отмена
          </button>
          <button
            type="button"
            @click="onApplyToProject"
            :disabled="isApplying || calibratedWords.length === 0"
            class="flex items-center space-x-1.5 px-5 py-2 text-xs font-semibold rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white shadow-md transition-colors disabled:opacity-40"
          >
            <Loader2 v-if="isApplying" class="w-4 h-4 animate-spin" />
            <Check v-else class="w-4 h-4" />
            <span>Применить в проект</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
