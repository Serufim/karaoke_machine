<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePipelineStore } from '@/stores/pipeline'
import { useModelsStore } from '@/stores/models'
import {
  X,
  Upload,
  Youtube,
  Settings2,
  FileAudio,
  HardDrive,
  CheckCircle,
  AlertCircle,
  Flame,
  Image as ImageIcon,
  RotateCcw,
  Sliders,
} from 'lucide-vue-next'

export interface EditProjectInitialData {
  projectTitle: string
  source?: string
  sourceType?: 'file' | 'url'
  referenceLyrics?: string
  coverPreviewUrl?: string
  modelSize?: string
  demucsModel?: string
  vadModel?: string
  useCtcAlign?: boolean
  useVideoBg?: boolean
  conditionOnPreviousText?: boolean
  strictRepeats?: boolean
  vocalVolumePct?: number
  numLines?: number
}

const props = withDefaults(
  defineProps<{
    mode?: 'create' | 'edit'
    initialQuery?: string
    initialCoverUrl?: string
    initialData?: EditProjectInitialData | null
  }>(),
  {
    mode: 'create',
    initialQuery: '',
    initialCoverUrl: '',
    initialData: null,
  }
)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'open-models'): void
  (e: 'open-charts'): void
}>()

const pipelineStore = usePipelineStore()
const modelsStore = useModelsStore()

const activeTab = ref<'file' | 'url'>('file')
const selectedFile = ref<File | null>(null)
const youtubeUrl = ref('')
const referenceLyrics = ref('')
const coverFile = ref<File | null>(null)
const coverPreview = ref<string | null>(null)

// Model options
const modelSize = ref('large-v3-turbo')
const demucsModel = ref('htdemucs')
const useCtcAlign = ref(false)
const useVideoBg = ref(false)
const conditionOnPreviousText = ref(false)
const vadModel = ref('auditok')
const strictRepeats = ref(false)
const vocalVolumePct = ref(0)
const numLines = ref(4)

onMounted(async () => {
  if (props.mode === 'edit' && props.initialData) {
    const d = props.initialData
    if (d.sourceType === 'url') {
      activeTab.value = 'url'
      youtubeUrl.value = d.source || ''
    } else {
      activeTab.value = 'file'
    }
    if (d.referenceLyrics) {
      referenceLyrics.value = d.referenceLyrics
    }
    if (d.coverPreviewUrl) {
      coverPreview.value = d.coverPreviewUrl
    }
    if (d.modelSize) modelSize.value = d.modelSize
    if (d.demucsModel) demucsModel.value = d.demucsModel
    if (d.vadModel) vadModel.value = d.vadModel
    if (d.useCtcAlign !== undefined) useCtcAlign.value = d.useCtcAlign
    if (d.useVideoBg !== undefined) useVideoBg.value = d.useVideoBg
    if (d.conditionOnPreviousText !== undefined) conditionOnPreviousText.value = d.conditionOnPreviousText
    if (d.strictRepeats !== undefined) strictRepeats.value = d.strictRepeats
    if (d.vocalVolumePct !== undefined) vocalVolumePct.value = d.vocalVolumePct
    if (d.numLines !== undefined) numLines.value = d.numLines
  } else {
    if (props.initialQuery) {
      youtubeUrl.value = props.initialQuery
      activeTab.value = 'url'
    }
    if (props.initialCoverUrl) {
      coverPreview.value = props.initialCoverUrl
    }
  }

  await Promise.all([
    modelsStore.fetchHardware(),
    modelsStore.fetchCatalog(),
  ])
  if (props.mode !== 'edit' && modelsStore.hardware) {
    if (modelsStore.hardware.recommended_whisper) {
      modelSize.value = modelsStore.hardware.recommended_whisper
    }
    if (modelsStore.hardware.recommended_demucs) {
      demucsModel.value = modelsStore.hardware.recommended_demucs
    }
  }
})


function onFileSelect(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    selectedFile.value = target.files[0]
  }
}

function onDrop(e: DragEvent) {
  e.preventDefault()
  if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
    selectedFile.value = e.dataTransfer.files[0]
    activeTab.value = 'file'
  }
}

function onCoverSelect(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    setCover(target.files[0])
  }
}

function onCoverDrop(e: DragEvent) {
  e.preventDefault()
  if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
    setCover(e.dataTransfer.files[0])
  }
}

function setCover(file: File) {
  if (!file.type.startsWith('image/')) {
    alert('Пожалуйста, выберите изображение (PNG, JPG, WebP).')
    return
  }
  coverFile.value = file
  const reader = new FileReader()
  reader.onload = (e) => {
    coverPreview.value = e.target?.result as string
  }
  reader.readAsDataURL(file)
}

function removeCover() {
  coverFile.value = null
  coverPreview.value = null
}

function onSubmit() {
  const formData = new FormData()

  if (props.mode === 'edit' && props.initialData?.projectTitle) {
    formData.append('existing_project_title', props.initialData.projectTitle)
  }

  if (activeTab.value === 'file') {
    if (selectedFile.value) {
      formData.append('file', selectedFile.value)
    } else if (props.mode !== 'edit') {
      alert('Пожалуйста, выберите аудио или видео файл.')
      return
    }
  } else {
    if (youtubeUrl.value.trim()) {
      formData.append('url', youtubeUrl.value.trim())
    } else if (props.mode !== 'edit') {
      alert('Пожалуйста, введите ссылку на YouTube.')
      return
    }
  }

  if (coverFile.value) {
    formData.append('bg_file', coverFile.value)
    formData.append('cover_file', coverFile.value)
  }

  formData.append('model_size', modelSize.value)
  formData.append('demucs_model', demucsModel.value)
  formData.append('language', 'ru')
  formData.append('reference_lyrics', referenceLyrics.value.trim())
  formData.append('use_ctc_align', String(useCtcAlign.value))
  formData.append('use_video_bg', String(useVideoBg.value))
  formData.append('condition_on_previous_text', String(conditionOnPreviousText.value))
  formData.append('vad', vadModel.value)
  formData.append('strict_repeats', String(strictRepeats.value))
  formData.append('vocal_volume_pct', String(vocalVolumePct.value))
  formData.append('num_lines', String(numLines.value))

  pipelineStore.startGenerate(formData)
  emit('close')
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
    <div class="w-full max-w-2xl bg-studio-panel border border-studio-border rounded-xl shadow-2xl flex flex-col overflow-hidden max-h-[92vh]">
      <!-- Header -->
      <div class="px-5 py-4 border-b border-studio-border flex items-center justify-between">
        <h2 class="text-base font-semibold text-white flex items-center space-x-2">
          <Sliders v-if="props.mode === 'edit'" class="w-4 h-4 text-sky-400" />
          <span>{{ props.mode === 'edit' ? `Параметры генерации: ${props.initialData?.projectTitle || ''}` : 'Создать новый караоке-проект' }}</span>
        </h2>
        <button @click="emit('close')" class="text-studio-muted hover:text-white transition-colors">
          <X class="w-5 h-5" />
        </button>
      </div>

      <!-- Body -->
      <div class="p-5 overflow-y-auto space-y-4 text-sm">
        <!-- Source Tabs -->
        <div class="flex rounded-lg bg-studio-surface p-1 border border-studio-border">
          <button
            @click="activeTab = 'file'"
            :class="[
              'flex-1 py-1.5 text-xs font-medium rounded-md flex items-center justify-center space-x-1.5 transition-colors',
              activeTab === 'file' ? 'bg-sky-600 text-white shadow' : 'text-studio-muted hover:text-white'
            ]"
          >
            <Upload class="w-3.5 h-3.5" />
            <span>Файл с ПК</span>
          </button>
          <button
            @click="activeTab = 'url'"
            :class="[
              'flex-1 py-1.5 text-xs font-medium rounded-md flex items-center justify-center space-x-1.5 transition-colors',
              activeTab === 'url' ? 'bg-sky-600 text-white shadow' : 'text-studio-muted hover:text-white'
            ]"
          >
            <Youtube class="w-3.5 h-3.5 text-red-400" />
            <span>YouTube / Поиск</span>
          </button>
          <button
            type="button"
            @click="emit('open-charts')"
            class="flex-1 py-1.5 text-xs font-medium rounded-md flex items-center justify-center space-x-1.5 text-amber-300 hover:text-amber-200 hover:bg-amber-500/10 transition-colors border border-amber-500/20"
          >
            <Flame class="w-3.5 h-3.5 text-amber-400" />
            <span>Из чартов</span>
          </button>
        </div>

        <!-- File Upload Area -->
        <div v-if="activeTab === 'file'">
          <!-- Existing project file banner in edit mode -->
          <div
            v-if="props.mode === 'edit' && !selectedFile && props.initialData?.projectTitle"
            class="border border-sky-500/40 bg-sky-500/10 rounded-xl p-4 flex items-center justify-between shadow-sm"
          >
            <div class="flex items-center space-x-3 min-w-0">
              <div class="w-10 h-10 rounded-lg bg-sky-500/20 border border-sky-500/30 flex items-center justify-center shrink-0">
                <FileAudio class="w-5 h-5 text-sky-400" />
              </div>
              <div class="min-w-0">
                <div class="flex items-center space-x-2">
                  <span class="text-xs font-semibold text-white truncate max-w-[280px]">{{ props.initialData.projectTitle }}</span>
                  <span class="text-[10px] px-1.5 py-0.5 rounded bg-sky-500/20 text-sky-300 border border-sky-500/40 font-medium">Текущий трек проекта</span>
                </div>
                <p class="text-[11px] text-slate-300 mt-0.5">Аудио сохранено в проекте. Загрузите файл только если хотите заменить его.</p>
              </div>
            </div>
            <button
              type="button"
              @click="($refs.fileInput as HTMLInputElement)?.click()"
              class="ml-3 shrink-0 px-3 py-1.5 text-xs font-medium rounded-lg bg-studio-surface hover:bg-slate-700 text-slate-200 border border-studio-border transition-colors shadow-sm"
            >
              Заменить файл...
            </button>
            <input
              ref="fileInput"
              type="file"
              accept="audio/*,video/*"
              @change="onFileSelect"
              class="hidden"
            />
          </div>

          <!-- Dropzone if creating or user wants to select a new file -->
          <div
            v-else
            @dragover.prevent
            @drop="onDrop"
            class="border-2 border-dashed border-studio-border hover:border-sky-500 rounded-xl p-6 text-center cursor-pointer transition-colors bg-studio-surface/30 relative"
            @click="($refs.fileInput as HTMLInputElement)?.click()"
          >
            <input
              ref="fileInput"
              type="file"
              accept="audio/*,video/*"
              @change="onFileSelect"
              class="hidden"
            />
            <FileAudio class="w-10 h-10 mx-auto text-sky-400/80 mb-2" />
            <div v-if="selectedFile" class="space-y-1">
              <p class="font-medium text-white truncate max-w-sm mx-auto">
                {{ selectedFile.name }}
              </p>
              <button
                v-if="props.mode === 'edit' && props.initialData?.projectTitle"
                type="button"
                @click.stop="selectedFile = null"
                class="text-[11px] text-sky-400 hover:text-sky-300 underline"
              >
                Вернуть исходный трек проекта
              </button>
            </div>
            <div v-else>
              <p class="font-medium text-slate-200">Перетащите аудио или видео сюда</p>
              <p class="text-xs text-studio-muted mt-1">MP3, WAV, FLAC, MP4, MKV</p>
            </div>
          </div>
        </div>

        <!-- URL Input Area -->
        <div v-else class="space-y-1">
          <div class="flex items-center justify-between">
            <label class="text-xs font-medium text-slate-300">Ссылка на YouTube или название трека:</label>
            <button
              type="button"
              @click="emit('open-charts')"
              class="text-[11px] text-amber-400 hover:text-amber-300 flex items-center space-x-1"
            >
              <Flame class="w-3 h-3" />
              <span>Выбрать из топов</span>
            </button>
          </div>
          <input
            v-model="youtubeUrl"
            type="text"
            placeholder="Ссылка на YouTube или 'Исполнитель - Трек' (поиск в 1 клик)"
            class="w-full bg-studio-surface border border-studio-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500"
          />
        </div>

        <!-- Reference Lyrics -->
        <div class="space-y-1">
          <label class="text-xs font-medium text-slate-300 flex justify-between">
            <span>Текст песни (необязательно):</span>
            <span class="text-studio-muted text-[10px]">Каждая строка станет строкой караоке</span>
          </label>
          <textarea
            v-model="referenceLyrics"
            rows="8"
            placeholder="Вставьте официальный текст песни (куплеты, припевы). Нейросеть идеально разобьет тайминги по вашим строкам..."
            class="w-full bg-studio-surface border border-studio-border rounded-lg p-3 text-xs text-white focus:outline-none focus:border-sky-500 font-mono resize-y min-h-[140px] max-h-[340px] leading-relaxed"
          ></textarea>
        </div>

        <!-- Custom Background Image with Preview -->
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-slate-300 flex justify-between">
            <span>Фоновое изображение (16:9 для видео, необязательно):</span>
            <span class="text-studio-muted text-[10px]">PNG, JPG, WebP — будет использовано как полноэкранный фон видео</span>
          </label>
          <div class="flex items-center space-x-3">
            <div
              v-if="coverPreview"
              class="relative w-20 h-12 rounded-lg overflow-hidden border border-studio-border shrink-0 group shadow-md"
            >
              <img :src="coverPreview" alt="Предпросмотр фона" class="w-full h-full object-cover" />
              <button
                type="button"
                @click="removeCover"
                class="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 flex items-center justify-center text-red-400 transition-opacity"
                title="Удалить фон"
              >
                <X class="w-4 h-4" />
              </button>
            </div>
            <div
              @dragover.prevent
              @drop="onCoverDrop"
              @click="($refs.coverInput as HTMLInputElement)?.click()"
              class="flex-1 border border-dashed border-studio-border hover:border-sky-500 rounded-lg p-3 text-center cursor-pointer transition-colors bg-studio-surface/20 flex items-center justify-center space-x-2"
            >
              <input
                ref="coverInput"
                type="file"
                accept="image/*"
                @change="onCoverSelect"
                class="hidden"
              />
              <ImageIcon class="w-4 h-4 text-sky-400 shrink-0" />
              <span v-if="coverFile" class="text-xs text-white font-medium truncate max-w-[280px]">
                {{ coverFile.name }}
              </span>
              <span v-else class="text-xs text-studio-muted">
                Нажмите для выбора или перетащите фоновое изображение сюда
              </span>
            </div>
          </div>
        </div>

        <!-- Advanced AI Settings -->
        <div class="pt-2 border-t border-studio-border space-y-3">
          <div class="flex items-center justify-between text-xs">
            <div class="flex items-center space-x-2 font-semibold text-slate-300">
              <Settings2 class="w-4 h-4 text-sky-400" />
              <span>Параметры нейросетей</span>
            </div>
            <button
              type="button"
              @click="emit('open-models')"
              class="text-sky-400 hover:text-sky-300 flex items-center space-x-1 text-[11px] font-medium"
            >
              <HardDrive class="w-3.5 h-3.5" />
              <span>Менеджер моделей...</span>
            </button>
          </div>

          <div class="grid grid-cols-3 gap-2.5 text-xs">
            <div>
              <label class="text-studio-muted block mb-1">Whisper модель:</label>
              <select
                v-model="modelSize"
                class="w-full bg-studio-surface border border-studio-border rounded px-2 py-1.5 text-white focus:outline-none"
              >
                <option value="large-v3-turbo">large-v3-turbo (быстро и точно)</option>
                <option value="bond005/whisper-podlodka-turbo">Podlodka Russian Turbo</option>
                <option value="antony66/whisper-large-v3-russian">Whisper Large V3 Russian</option>
                <option value="large-v3">large-v3 (максимум точности)</option>
                <option value="medium">medium</option>
                <option value="small">small</option>
              </select>
            </div>

            <div>
              <label class="text-studio-muted block mb-1">Demucs разделение:</label>
              <select
                v-model="demucsModel"
                class="w-full bg-studio-surface border border-studio-border rounded px-2 py-1.5 text-white focus:outline-none"
              >
                <option value="htdemucs">htdemucs (быстрый)</option>
                <option value="htdemucs_ft">htdemucs_ft (чистый вокал)</option>
                <option value="mdx_extra">mdx_extra</option>
              </select>
            </div>

            <div>
              <label class="text-studio-muted block mb-1">VAD-фильтр тишины:</label>
              <select
                v-model="vadModel"
                class="w-full bg-studio-surface border border-studio-border rounded px-2 py-1.5 text-white focus:outline-none"
              >
                <option value="auditok">auditok (рекомендуется)</option>
                <option value="silero">silero</option>
                <option value="none">без VAD</option>
              </select>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-2 pt-1 text-xs">
            <label class="flex items-center space-x-2 cursor-pointer">
              <input type="checkbox" v-model="useCtcAlign" class="rounded bg-studio-surface border-studio-border text-sky-500" />
              <span class="text-slate-300">CTC Wav2Vec2 русское выравнивание</span>
            </label>

            <label class="flex items-center space-x-2 cursor-pointer">
              <input type="checkbox" v-model="useVideoBg" class="rounded bg-studio-surface border-studio-border text-sky-500" />
              <span class="text-slate-300">Сохранять фоновое видео</span>
            </label>

            <label class="flex items-center space-x-2 cursor-pointer" title="По умолчанию выключено для исключения зацикливания галлюцинаций Whisper в песнях">
              <input type="checkbox" v-model="conditionOnPreviousText" class="rounded bg-studio-surface border-studio-border text-sky-500" />
              <span class="text-slate-300">Учитывать контекст фраз Whisper</span>
            </label>

            <label class="flex items-center space-x-2 cursor-pointer" title="При несовпадении числа припевов с аудио отбрасывать готовый текст и переключаться на чистое распознавание">
              <input type="checkbox" v-model="strictRepeats" class="rounded bg-studio-surface border-studio-border text-sky-500" />
              <span class="text-slate-300">Строгая проверка повторов припевов</span>
            </label>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="px-5 py-3 border-t border-studio-border bg-studio-surface/40 flex justify-end space-x-3">
        <button
          @click="emit('close')"
          class="px-4 py-2 text-xs font-medium rounded-lg text-slate-300 hover:text-white hover:bg-studio-surface transition-colors"
        >
          Отмена
        </button>
        <button
          @click="onSubmit"
          class="px-5 py-2 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white shadow-md transition-colors flex items-center space-x-1.5"
        >
          <Sliders v-if="props.mode === 'edit'" class="w-3.5 h-3.5" />
          <span>{{ props.mode === 'edit' ? 'Перегенерировать трек' : 'Начать генерацию' }}</span>
        </button>
      </div>
    </div>
  </div>
</template>
