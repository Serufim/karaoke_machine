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
} from 'lucide-vue-next'

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'open-models'): void
}>()

const pipelineStore = usePipelineStore()
const modelsStore = useModelsStore()

const activeTab = ref<'file' | 'url'>('file')
const selectedFile = ref<File | null>(null)
const youtubeUrl = ref('')
const referenceLyrics = ref('')

// Model options
const modelSize = ref('large-v3-turbo')
const demucsModel = ref('htdemucs')
const useCtcAlign = ref(false)
const useVideoBg = ref(false)
const vocalVolumePct = ref(0)
const numLines = ref(4)

onMounted(async () => {
  await Promise.all([
    modelsStore.fetchHardware(),
    modelsStore.fetchCatalog(),
  ])
  if (modelsStore.hardware) {
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

function onSubmit() {
  const formData = new FormData()
  if (activeTab.value === 'file') {
    if (!selectedFile.value) {
      alert('Пожалуйста, выберите аудио или видео файл.')
      return
    }
    formData.append('file', selectedFile.value)
  } else {
    if (!youtubeUrl.value.trim()) {
      alert('Пожалуйста, введите ссылку на YouTube.')
      return
    }
    formData.append('url', youtubeUrl.value.trim())
  }

  formData.append('model_size', modelSize.value)
  formData.append('demucs_model', demucsModel.value)
  formData.append('language', 'ru')
  formData.append('reference_lyrics', referenceLyrics.value.trim())
  formData.append('use_ctc_align', String(useCtcAlign.value))
  formData.append('use_video_bg', String(useVideoBg.value))
  formData.append('vocal_volume_pct', String(vocalVolumePct.value))
  formData.append('num_lines', String(numLines.value))

  pipelineStore.startGenerate(formData)
  emit('close')
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
    <div class="w-full max-w-xl bg-studio-panel border border-studio-border rounded-xl shadow-2xl flex flex-col overflow-hidden max-h-[90vh]">
      <!-- Header -->
      <div class="px-5 py-4 border-b border-studio-border flex items-center justify-between">
        <h2 class="text-base font-semibold text-white flex items-center space-x-2">
          <span>Создать новый караоке-проект</span>
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
              'flex-1 py-1.5 text-xs font-medium rounded-md flex items-center justify-center space-x-2 transition-colors',
              activeTab === 'file' ? 'bg-sky-600 text-white shadow' : 'text-studio-muted hover:text-white'
            ]"
          >
            <Upload class="w-4 h-4" />
            <span>Файл с компьютера</span>
          </button>
          <button
            @click="activeTab = 'url'"
            :class="[
              'flex-1 py-1.5 text-xs font-medium rounded-md flex items-center justify-center space-x-2 transition-colors',
              activeTab === 'url' ? 'bg-sky-600 text-white shadow' : 'text-studio-muted hover:text-white'
            ]"
          >
            <Youtube class="w-4 h-4 text-red-400" />
            <span>YouTube ссылка</span>
          </button>
        </div>

        <!-- File Upload Area -->
        <div
          v-if="activeTab === 'file'"
          @dragover.prevent
          @drop="onDrop"
          class="border-2 border-dashed border-studio-border hover:border-sky-500 rounded-xl p-6 text-center cursor-pointer transition-colors bg-studio-surface/30"
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
          <p v-if="selectedFile" class="font-medium text-white truncate max-w-sm mx-auto">
            {{ selectedFile.name }}
          </p>
          <div v-else>
            <p class="font-medium text-slate-200">Перетащите аудио или видео сюда</p>
            <p class="text-xs text-studio-muted mt-1">MP3, WAV, FLAC, MP4, MKV</p>
          </div>
        </div>

        <!-- URL Input Area -->
        <div v-else class="space-y-1">
          <label class="text-xs font-medium text-slate-300">Ссылка на YouTube трек:</label>
          <input
            v-model="youtubeUrl"
            type="text"
            placeholder="https://www.youtube.com/watch?v=..."
            class="w-full bg-studio-surface border border-studio-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-sky-500"
          />
        </div>

        <!-- Reference Lyrics -->
        <div class="space-y-1">
          <label class="text-xs font-medium text-slate-300 flex justify-between">
            <span>Эталонный текст песни (необязательно):</span>
            <span class="text-studio-muted text-[10px]">Для точного выравнивания слов</span>
          </label>
          <textarea
            v-model="referenceLyrics"
            rows="3"
            placeholder="Вставьте официальный текст песни..."
            class="w-full bg-studio-surface border border-studio-border rounded-lg p-2.5 text-xs text-white focus:outline-none focus:border-sky-500 font-mono resize-none"
          ></textarea>
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


          <div class="grid grid-cols-2 gap-3 text-xs">
            <div>
              <label class="text-studio-muted block mb-1">Whisper модель:</label>
              <select
                v-model="modelSize"
                class="w-full bg-studio-surface border border-studio-border rounded px-2.5 py-1.5 text-white focus:outline-none"
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
                class="w-full bg-studio-surface border border-studio-border rounded px-2.5 py-1.5 text-white focus:outline-none"
              >
                <option value="htdemucs">htdemucs (быстрый)</option>
                <option value="htdemucs_ft">htdemucs_ft (чистый вокал)</option>
                <option value="mdx_extra">mdx_extra</option>
              </select>
            </div>
          </div>

          <div class="flex items-center space-x-4 pt-1 text-xs">
            <label class="flex items-center space-x-2 cursor-pointer">
              <input type="checkbox" v-model="useCtcAlign" class="rounded bg-studio-surface border-studio-border" />
              <span class="text-slate-300">CTC Wav2Vec2 русское выравнивание</span>
            </label>

            <label class="flex items-center space-x-2 cursor-pointer">
              <input type="checkbox" v-model="useVideoBg" class="rounded bg-studio-surface border-studio-border" />
              <span class="text-slate-300">Сохранять фоновое видео</span>
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
          class="px-5 py-2 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white shadow-md transition-colors"
        >
          Начать генерацию
        </button>
      </div>
    </div>
  </div>
</template>
