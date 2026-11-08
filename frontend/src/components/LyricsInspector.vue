<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useProjectStore } from '@/stores/project'
import { usePipelineStore } from '@/stores/pipeline'
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

    <!-- Cover Art Card / Quick Uploader -->
    <div
      v-if="projectStore.hasProject"
      class="p-3 bg-studio-surface/40 border-b border-studio-border flex flex-col space-y-2"
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
    <div class="p-2.5 bg-studio-surface/50 border-b border-studio-border flex flex-col space-y-1.5">
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

      <button
        @click="handleRealignTimings"
        :disabled="!projectStore.hasProject || isProcessingTool"
        class="w-full flex items-center justify-center space-x-1.5 py-1.5 px-2 rounded text-xs font-medium bg-studio-surface hover:bg-slate-700 text-emerald-300 border border-studio-border disabled:opacity-40 transition-colors"
        title="Акустически пересчитать таймкоды [MM:SS.cc -> MM:SS.cc] для строк по вокалу"
      >
        <Clock :class="['w-3.5 h-3.5 text-emerald-400', isProcessingTool ? 'animate-spin' : '']" />
        <span>Пересчитать тайминги текста</span>
      </button>

      <button
        @click="handleRegroupLines"
        :disabled="!projectStore.hasProject || isProcessingTool"
        class="w-full flex items-center justify-center space-x-1.5 py-1.5 px-2 rounded text-xs font-medium bg-studio-surface hover:bg-slate-700 text-sky-300 border border-studio-border disabled:opacity-40 transition-colors"
      >
        <Sparkles class="w-3.5 h-3.5 text-sky-400" />
        <span>Склеить короткие строки</span>
      </button>

      <button
        @click="handleSplitLongLines"
        :disabled="!projectStore.hasProject || isProcessingTool"
        class="w-full flex items-center justify-center space-x-1.5 py-1.5 px-2 rounded text-xs font-medium bg-studio-surface hover:bg-slate-700 text-amber-300 border border-studio-border disabled:opacity-40 transition-colors"
      >
        <Scissors class="w-3.5 h-3.5 text-amber-400" />
        <span>Разделить длинные строки</span>
      </button>

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
    <div class="flex-1 p-2 flex flex-col min-h-0">
      <textarea
        v-model="localText"
        @input="onTextChange"
        placeholder="Текст караоке с таймингами..."
        class="flex-1 w-full bg-studio-bg border border-studio-border/70 rounded p-2 text-xs font-mono text-slate-200 resize-none focus:outline-none focus:border-sky-500 leading-relaxed"
      ></textarea>
      <div class="text-[10px] text-studio-muted mt-1 px-1 flex justify-between">
        <span>Формат: [00:12.30 -> 00:16.80] Текст</span>
        <span>{{ projectStore.currentProject?.lines?.length || 0 }} строк</span>
      </div>
    </div>
  </aside>
</template>
