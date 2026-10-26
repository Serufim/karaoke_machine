<script setup lang="ts">
import { ref, computed } from 'vue'
import { useProjectStore } from '@/stores/project'
import { usePipelineStore } from '@/stores/pipeline'
import { X, Video, Sliders, Upload, Image as ImageIcon, Camera } from 'lucide-vue-next'

const emit = defineEmits<{
  (e: 'close'): void
}>()

const projectStore = useProjectStore()
const pipelineStore = usePipelineStore()

const videoQuality = ref('balanced')
const vocalVolumePct = ref(0)
const numLines = ref(4)
const bgMode = ref<'cover' | 'custom' | 'video'>('cover')
const visualEffects = ref('sparkles_pulse')
const edgeColorMode = ref('cyberpunk')
const fontSizeMode = ref('large')
const highlightColor = ref('gold_neon')

const coverInputRef = ref<HTMLInputElement | null>(null)
const bgInputRef = ref<HTMLInputElement | null>(null)
const uploadStatus = ref('')

const coverUrl = computed(() => {
  if (!projectStore.currentProject?.title) return ''
  return `/api/media/${encodeURIComponent(projectStore.currentProject.title)}/cover?t=${projectStore.coverTimestamp}`
})

async function onCoverChange(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    try {
      uploadStatus.value = 'Загрузка обложки...'
      await projectStore.uploadCover(target.files[0])
      uploadStatus.value = 'Обложка успешно обновлена!'
      setTimeout(() => { uploadStatus.value = '' }, 3000)
    } catch (err: any) {
      uploadStatus.value = err.message || 'Ошибка загрузки'
    }
  }
}

async function onCustomBgChange(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    try {
      uploadStatus.value = 'Загрузка фона...'
      await projectStore.uploadBackground(target.files[0])
      uploadStatus.value = 'Полноэкранный фон загружен!'
      setTimeout(() => { uploadStatus.value = '' }, 3000)
    } catch (err: any) {
      uploadStatus.value = err.message || 'Ошибка загрузки'
    }
  }
}

function onSubmit() {
  if (!projectStore.currentProject) return

  pipelineStore.startRebuild({
    title: projectStore.currentProject.title,
    editor_text: projectStore.currentProject.editor_text,
    vocal_volume: vocalVolumePct.value / 100,
    vocal_intervals: projectStore.currentProject.vocal_intervals,
    fx_intervals: projectStore.currentProject.fx_intervals,
    emoji_intervals: projectStore.currentProject.emoji_intervals || [],
    num_lines: numLines.value,
    video_quality: videoQuality.value,
    use_cover_bg: bgMode.value === 'cover',
    use_video_bg: bgMode.value === 'video',
    visual_effects: visualEffects.value,
    edge_color_mode: edgeColorMode.value,
    font_size_mode: fontSizeMode.value,
    highlight_color: highlightColor.value,
  })

  emit('close')
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
    <div class="w-full max-w-lg bg-studio-panel border border-studio-border rounded-xl shadow-2xl flex flex-col overflow-hidden">
      <!-- Header -->
      <div class="px-5 py-4 border-b border-studio-border flex items-center justify-between">
        <h2 class="text-base font-semibold text-white flex items-center space-x-2">
          <Video class="w-5 h-5 text-sky-400" />
          <span>Параметры рендеринга MP4</span>
        </h2>
        <button @click="emit('close')" class="text-studio-muted hover:text-white transition-colors">
          <X class="w-5 h-5" />
        </button>
      </div>

      <!-- Body -->
      <div class="p-5 space-y-4 text-xs">
        <!-- Quality Preset -->
        <div>
          <label class="text-slate-300 font-medium block mb-1.5">Качество видео (Full HD 1080p):</label>
          <div class="grid grid-cols-3 gap-2">
            <button
              v-for="q in [
                { id: 'balanced', label: 'Balanced', desc: 'CRF 22' },
                { id: 'high', label: 'High', desc: 'CRF 18' },
                { id: 'master', label: 'Master', desc: 'CRF 14' }
              ]"
              :key="q.id"
              type="button"
              @click="videoQuality = q.id"
              :class="[
                'p-2.5 rounded-lg border text-center transition-all',
                videoQuality === q.id
                  ? 'border-sky-500 bg-sky-600/20 text-white font-semibold'
                  : 'border-studio-border bg-studio-surface text-studio-muted hover:text-white'
              ]"
            >
              <div class="text-xs">{{ q.label }}</div>
              <div class="text-[10px] opacity-60">{{ q.desc }}</div>
            </button>
          </div>
        </div>

        <!-- Vocal Volume in Video -->
        <div>
          <div class="flex justify-between mb-1">
            <label class="text-slate-300 font-medium">Громкость голоса в готовом видео:</label>
            <span class="font-mono text-sky-400 font-semibold">{{ vocalVolumePct }}%</span>
          </div>
          <input
            type="range"
            min="0"
            max="100"
            step="5"
            v-model.number="vocalVolumePct"
            class="w-full bg-slate-700 h-1.5 rounded cursor-pointer"
          />
          <div class="flex justify-between text-[10px] text-studio-muted mt-1">
            <span>0% (Чистый минус)</span>
            <span>10% (Бэк-вокал)</span>
            <span>100% (Оригинал)</span>
          </div>
        </div>

        <!-- Subtitle Styling -->
        <div class="pt-3 border-t border-studio-border space-y-3">
          <div class="flex items-center space-x-1.5 font-medium text-slate-300">
            <Sliders class="w-3.5 h-3.5 text-sky-400" />
            <span>Оформление субтитров</span>
          </div>

          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="text-studio-muted block mb-1">Строк на экране:</label>
              <select
                v-model.number="numLines"
                class="w-full bg-studio-surface border border-studio-border rounded px-2 py-1.5 text-white focus:outline-none"
              >
                <option :value="2">2 строки</option>
                <option :value="3">3 строки</option>
                <option :value="4">4 строки (стандарт)</option>
              </select>
            </div>

            <div>
              <label class="text-studio-muted block mb-1">Цвет подсветки текста:</label>
              <select
                v-model="highlightColor"
                class="w-full bg-studio-surface border border-studio-border rounded px-2.5 py-1.5 text-white focus:outline-none"
              >
                <option value="gold_neon">Золотой неон (#FFD700)</option>
                <option value="green_neon">🟢 Зеленый неон (Acid Lime)</option>
                <option value="emerald">Изумрудный (Deep Emerald)</option>
                <option value="electric_cyan">Бирюзовое сияние (#00F0FF)</option>
                <option value="neon_magenta">Неоновый розовый (#FF1493)</option>
                <option value="fire_orange">Огненный оранжевый (#FF6A00)</option>
              </select>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-3 pt-1">
            <div>
              <label class="text-studio-muted block mb-1">Стиль рамки (Ambilight):</label>
              <select
                v-model="edgeColorMode"
                class="w-full bg-studio-surface border border-studio-border rounded px-2.5 py-1.5 text-white focus:outline-none"
              >
                <option value="cyberpunk">Киберпанк (стандарт)</option>
                <option value="green_neon">🟢 Зеленый неон</option>
                <option value="police">🚨 Полицейская мигалка (бегущие огни)</option>
                <option value="neon_rainbow">Радужные переливы</option>
                <option value="cover_colors">Цвета обложки трека</option>
                <option value="fire">Огонь</option>
              </select>
            </div>

            <div>
              <label class="text-studio-muted block mb-1">Базовый спецэффект:</label>
              <select
                v-model="visualEffects"
                class="w-full bg-studio-surface border border-studio-border rounded px-2.5 py-1.5 text-white focus:outline-none"
              >
                <option value="sparkles_pulse">Неон-рамка + Блестки</option>
                <option value="police_strobe">🚨 Мигалка + Бегущие огни</option>
                <option value="green_neon">🟢 Зеленый неон</option>
                <option value="sparkles">Только блестки</option>
                <option value="climax">Климакс (двойной неон)</option>
                <option value="none">Без эффектов</option>
              </select>
            </div>
          </div>

          <!-- Background Source & Image Uploader -->
          <div class="pt-2 border-t border-studio-border space-y-2">
            <label class="text-slate-300 font-medium block">Фон видеокараоке:</label>

            <div class="grid grid-cols-3 gap-2">
              <button
                type="button"
                @click="bgMode = 'cover'"
                :class="[
                  'p-2 rounded-lg border text-left transition-all flex flex-col justify-between',
                  bgMode === 'cover'
                    ? 'border-sky-500 bg-sky-600/20 text-white font-semibold'
                    : 'border-studio-border bg-studio-surface text-studio-muted hover:text-white'
                ]"
              >
                <span>Обложка (Ambilight)</span>
                <span class="text-[10px] opacity-60">Размытие + карточка</span>
              </button>

              <button
                type="button"
                @click="bgMode = 'custom'"
                :class="[
                  'p-2 rounded-lg border text-left transition-all flex flex-col justify-between',
                  bgMode === 'custom'
                    ? 'border-sky-500 bg-sky-600/20 text-white font-semibold'
                    : 'border-studio-border bg-studio-surface text-studio-muted hover:text-white'
                ]"
              >
                <span>Свой фон 1080p</span>
                <span class="text-[10px] opacity-60">Картинка на весь экран</span>
              </button>

              <button
                type="button"
                @click="bgMode = 'video'"
                :class="[
                  'p-2 rounded-lg border text-left transition-all flex flex-col justify-between',
                  bgMode === 'video'
                    ? 'border-sky-500 bg-sky-600/20 text-white font-semibold'
                    : 'border-studio-border bg-studio-surface text-studio-muted hover:text-white'
                ]"
              >
                <span>Видео YouTube</span>
                <span class="text-[10px] opacity-60">Исходный клип</span>
              </button>
            </div>

            <!-- Cover Attachment View in Modal -->
            <div v-if="bgMode === 'cover'" class="p-2.5 rounded-lg bg-studio-surface/50 border border-studio-border flex items-center justify-between">
              <div class="flex items-center space-x-2.5">
                <img
                  v-if="coverUrl"
                  :src="coverUrl"
                  class="w-10 h-10 rounded object-cover border border-studio-border shrink-0 bg-black"
                />
                <div class="text-[11px]">
                  <div class="text-white font-medium">Обложка проекта</div>
                  <div class="text-studio-muted">Используется для Ambilight и карточки</div>
                </div>
              </div>

              <input
                ref="coverInputRef"
                type="file"
                accept="image/*"
                class="hidden"
                @change="onCoverChange"
              />
              <button
                type="button"
                @click="coverInputRef?.click()"
                class="px-2.5 py-1.5 rounded bg-studio-surface hover:bg-slate-700 text-sky-400 border border-studio-border text-xs font-medium flex items-center space-x-1 transition-colors"
              >
                <Camera class="w-3.5 h-3.5" />
                <span>Заменить обложку</span>
              </button>
            </div>

            <!-- Custom Background Uploader -->
            <div v-else-if="bgMode === 'custom'" class="p-2.5 rounded-lg bg-studio-surface/50 border border-studio-border flex items-center justify-between">
              <div class="text-[11px]">
                <div class="text-white font-medium">Полноэкранный фон 1080p</div>
                <div class="text-studio-muted">Загрузите картинку или видео для заднего плана</div>
              </div>

              <input
                ref="bgInputRef"
                type="file"
                accept="image/*,video/*"
                class="hidden"
                @change="onCustomBgChange"
              />
              <button
                type="button"
                @click="bgInputRef?.click()"
                class="px-2.5 py-1.5 rounded bg-studio-surface hover:bg-slate-700 text-sky-400 border border-studio-border text-xs font-medium flex items-center space-x-1 transition-colors"
              >
                <Upload class="w-3.5 h-3.5" />
                <span>Загрузить фон</span>
              </button>
            </div>

            <div v-if="uploadStatus" class="text-[11px] font-medium text-emerald-400 bg-emerald-500/10 px-2 py-1 rounded border border-emerald-500/20">
              {{ uploadStatus }}
            </div>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="px-5 py-3 border-t border-studio-border bg-studio-surface/40 flex justify-end space-x-3">
        <button
          @click="emit('close')"
          class="px-4 py-2 text-xs font-medium rounded-lg text-slate-300 hover:text-white transition-colors"
        >
          Отмена
        </button>
        <button
          @click="onSubmit"
          class="px-5 py-2 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white shadow transition-colors flex items-center space-x-1.5"
        >
          <Video class="w-3.5 h-3.5" />
          <span>Начать пересборку</span>
        </button>
      </div>
    </div>
  </div>
</template>
