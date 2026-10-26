<script setup lang="ts">
import { ref, computed } from 'vue'
import { useProjectStore } from '@/stores/project'
import { usePipelineStore } from '@/stores/pipeline'
import { usePlayerStore } from '@/stores/player'
import { X, Video, Sliders, Upload, Camera, Disc, Download, Sparkles } from 'lucide-vue-next'

const emit = defineEmits<{
  (e: 'close'): void
}>()

const projectStore = useProjectStore()
const pipelineStore = usePipelineStore()
const playerStore = usePlayerStore()

const videoQuality = ref('balanced')
const vocalVolumePct = ref(Math.min(100, Math.round((playerStore.liveVocalMultiplier || 0) * 100)))
const numLines = ref(4)
const bgMode = ref<'cover' | 'custom' | 'video'>('cover')
const visualEffects = ref('sparkles_pulse')
const edgeColorMode = ref('cyberpunk')
const fontSizeMode = ref('large')
const highlightColor = ref('gold_neon')
const dualAudioMp4 = ref(true)
const watermarkText = ref(projectStore.currentProject?.watermark_text || '')
const isExportingDjPack = ref(false)
const djPackResult = ref<{ dj_pack_url: string; kfn_url: string; dj_pack_filename: string; kfn_filename: string } | null>(null)
const djExportError = ref('')

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

async function onSubmit() {
  if (!projectStore.currentProject) return

  // Automatically save current timeline state (vocal_intervals, fx_intervals, editor_text)
  // before starting rebuild so nothing is lost upon reload
  try {
    await projectStore.saveProject()
  } catch (_) {}

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
    dual_audio_mp4: dualAudioMp4.value,
    watermark_text: watermarkText.value.trim() || null,
  })

  emit('close')
}

async function onBuildDjPack() {
  if (!projectStore.currentProject) return
  isExportingDjPack.value = true
  djExportError.value = ''
  djPackResult.value = null
  try {
    const res = await fetch(`/api/projects/${encodeURIComponent(projectStore.currentProject.title)}/export-dj-pack`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        editor_text: projectStore.currentProject.editor_text,
        vocal_volume: vocalVolumePct.value / 100,
        vocal_intervals: projectStore.currentProject.vocal_intervals,
      }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Ошибка сборки DJ-пака')
    }
    djPackResult.value = await res.json()
  } catch (e: any) {
    djExportError.value = e.message || 'Ошибка при экспорте DJ-пака'
  } finally {
    isExportingDjPack.value = false
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
    <div class="w-full max-w-lg bg-studio-panel border border-studio-border rounded-xl shadow-2xl flex flex-col overflow-hidden">
      <!-- Header -->
      <div class="px-5 py-4 border-b border-studio-border flex items-center justify-between bg-gradient-to-r from-amber-500/10 via-studio-panel to-studio-panel">
        <h2 class="text-base font-semibold text-white flex items-center space-x-2">
          <Sparkles class="w-5 h-5 text-amber-400 drop-shadow-[0_0_8px_rgba(245,158,11,0.6)]" />
          <span class="bg-gradient-to-r from-amber-200 via-amber-300 to-yellow-100 bg-clip-text text-transparent font-bold">Параметры рендеринга MP4</span>
        </h2>
        <button @click="emit('close')" class="text-studio-muted hover:text-white transition-colors">
          <X class="w-5 h-5" />
        </button>
      </div>

      <!-- Body -->
      <div class="p-5 space-y-4 text-xs max-h-[78vh] overflow-y-auto">
        <!-- Quality Preset -->
        <div>
          <label class="text-slate-300 font-medium block mb-1.5 flex items-center justify-between">
            <span>Качество видео (Full HD 1080p):</span>
            <span class="text-[10px] text-amber-400 font-medium uppercase tracking-wider">Пресеты битрейта</span>
          </label>
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
                  ? 'border-amber-500 bg-amber-500/20 text-amber-200 font-semibold gold-glow'
                  : 'border-studio-border bg-studio-surface text-studio-muted hover:text-white hover:border-amber-500/40'
              ]"
            >
              <div class="text-xs">{{ q.label }}</div>
              <div class="text-[10px] opacity-75">{{ q.desc }}</div>
            </button>
          </div>
        </div>

        <!-- Vocal Volume in Video -->
        <div>
          <div class="flex justify-between mb-1">
            <label class="text-slate-300 font-medium">Громкость голоса в готовом видео:</label>
            <span class="font-mono text-amber-400 font-bold">{{ vocalVolumePct }}%</span>
          </div>
          <input
            type="range"
            min="0"
            max="100"
            step="5"
            v-model.number="vocalVolumePct"
            class="w-full bg-slate-700 h-1.5 rounded cursor-pointer gold-range"
          />
          <div class="flex justify-between text-[10px] text-studio-muted mt-1">
            <span>0% (Чистый минус)</span>
            <span>10% (Бэк-вокал)</span>
            <span>100% (Оригинал)</span>
          </div>
        </div>

        <!-- Subtitle Styling -->
        <div class="pt-3 border-t border-studio-border space-y-3">
          <div class="flex items-center space-x-1.5 font-medium text-amber-300">
            <Sliders class="w-3.5 h-3.5 text-amber-400" />
            <span>Оформление субтитров и подсветки</span>
          </div>

          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="text-studio-muted block mb-1">Строк на экране:</label>
              <select
                v-model.number="numLines"
                class="w-full bg-studio-surface border border-studio-border rounded px-2 py-1.5 text-white focus:outline-none gold-select"
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
                class="w-full bg-studio-surface border border-studio-border rounded px-2.5 py-1.5 text-white focus:outline-none gold-select font-medium"
              >
                <option value="gold_neon">✨ Золотой неон (#FFD700)</option>
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
                class="w-full bg-studio-surface border border-studio-border rounded px-2.5 py-1.5 text-white focus:outline-none gold-select"
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
                class="w-full bg-studio-surface border border-studio-border rounded px-2.5 py-1.5 text-white focus:outline-none gold-select"
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
                    ? 'border-amber-500 bg-amber-500/20 text-amber-200 font-semibold gold-glow'
                    : 'border-studio-border bg-studio-surface text-studio-muted hover:text-white hover:border-amber-500/40'
                ]"
              >
                <span>Обложка (Ambilight)</span>
                <span class="text-[10px] opacity-70">Размытие + карточка</span>
              </button>

              <button
                type="button"
                @click="bgMode = 'custom'"
                :class="[
                  'p-2 rounded-lg border text-left transition-all flex flex-col justify-between',
                  bgMode === 'custom'
                    ? 'border-amber-500 bg-amber-500/20 text-amber-200 font-semibold gold-glow'
                    : 'border-studio-border bg-studio-surface text-studio-muted hover:text-white hover:border-amber-500/40'
                ]"
              >
                <span>Свой фон 1080p</span>
                <span class="text-[10px] opacity-70">Картинка на весь экран</span>
              </button>

              <button
                type="button"
                @click="bgMode = 'video'"
                :class="[
                  'p-2 rounded-lg border text-left transition-all flex flex-col justify-between',
                  bgMode === 'video'
                    ? 'border-amber-500 bg-amber-500/20 text-amber-200 font-semibold gold-glow'
                    : 'border-studio-border bg-studio-surface text-studio-muted hover:text-white hover:border-amber-500/40'
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

          <!-- Professional DJ / KJ Club Export & Branding -->
          <div class="pt-3 border-t border-studio-border space-y-2.5">
            <div class="flex items-center space-x-1.5 font-medium text-amber-400">
              <Disc class="w-3.5 h-3.5" />
              <span>Проф. оборудование, DJ-плееры и брендинг клуба</span>
            </div>

            <label class="flex items-start space-x-2 cursor-pointer bg-studio-surface/60 p-2 rounded-lg border border-studio-border">
              <input
                type="checkbox"
                v-model="dualAudioMp4"
                class="mt-0.5 rounded border-slate-600 text-sky-500 focus:ring-0"
              />
              <div>
                <div class="text-white font-medium">🎚️ Dual-Audio MP4 (2 аудиодорожки: Минус + Плюс 100%)</div>
                <div class="text-[10px] text-studio-muted">
                  Позволяет диджею в EnCore!, VirtualDJ или VLC в 1 клик переключать звук с минуса на голос певца без остановки видео
                </div>
              </div>
            </label>

            <div>
              <label class="text-studio-muted block mb-1">🏷️ Водяной знак / Брендинг DJ или караоке-бара (в углу экрана):</label>
              <input
                type="text"
                v-model="watermarkText"
                placeholder="Например: Karaoke by DJ Alex · Заказ песен: @djalex"
                class="w-full bg-studio-surface border border-studio-border rounded px-2.5 py-1.5 text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
              />
            </div>

            <div class="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/30 space-y-2">
              <div class="flex items-center justify-between">
                <div>
                  <div class="text-amber-300 font-semibold">📦 Универсальный DJ Master Pack (без ожидания видео)</div>
                  <div class="text-[10px] text-slate-300">
                    Собирает .KFN (EnCore!/KaraFun), MP3+G (.CDG.zip для VirtualDJ/OpenKJ), Enhanced .LRC, UltraStar .TXT и MP3 стемы
                  </div>
                </div>
                <button
                  type="button"
                  :disabled="isExportingDjPack"
                  @click="onBuildDjPack"
                  class="px-3 py-1.5 rounded-lg bg-amber-500 hover:bg-amber-400 disabled:opacity-50 text-slate-950 font-semibold text-xs shrink-0 flex items-center space-x-1 transition-colors"
                >
                  <Sparkles class="w-3.5 h-3.5" />
                  <span>{{ isExportingDjPack ? 'Сборка...' : 'Собрать DJ-пак' }}</span>
                </button>
              </div>

              <div v-if="djExportError" class="text-[11px] text-rose-400">
                {{ djExportError }}
              </div>

              <div v-if="djPackResult" class="flex flex-wrap gap-2 pt-1">
                <a
                  :href="djPackResult.dj_pack_url"
                  :download="djPackResult.dj_pack_filename"
                  class="px-2.5 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-[11px] flex items-center space-x-1"
                >
                  <Download class="w-3 h-3" />
                  <span>Скачать {{ djPackResult.dj_pack_filename }} (Все форматы)</span>
                </a>
                <a
                  :href="djPackResult.kfn_url"
                  :download="djPackResult.kfn_filename"
                  class="px-2.5 py-1 rounded bg-sky-600 hover:bg-sky-500 text-white font-medium text-[11px] flex items-center space-x-1"
                >
                  <Download class="w-3 h-3" />
                  <span>Скачать .KFN (EnCore! / KaraFun)</span>
                </a>
              </div>
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
          class="px-5 py-2 text-xs font-bold rounded-lg bg-gradient-to-r from-amber-500 via-amber-400 to-amber-500 hover:from-amber-400 hover:to-amber-300 text-slate-950 shadow-lg shadow-amber-500/25 transition-all flex items-center space-x-1.5"
        >
          <Video class="w-3.5 h-3.5 fill-current" />
          <span>Начать пересборку</span>
        </button>
      </div>
    </div>
  </div>
</template>
