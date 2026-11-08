<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useProjectStore } from '@/stores/project'
import { usePlayerStore } from '@/stores/player'
import {
  Play,
  Pause,
  Repeat,
  Volume2,
  VolumeX,
  Mic2,
  SkipBack,
} from 'lucide-vue-next'

const projectStore = useProjectStore()
const playerStore = usePlayerStore()

const videoRef = ref<HTMLVideoElement | null>(null)
const audioRef = ref<HTMLAudioElement | null>(null)
const isMuted = ref(false)
const mediaCacheBuster = ref(Date.now())
const lastVocalMultiplier = ref(0.8)

const hasVideoFile = computed(() => {
  return Boolean(projectStore.currentProject?.has_video)
})

const videoUrl = computed(() => {
  if (!projectStore.currentProject?.title) return ''
  const titleEnc = encodeURIComponent(projectStore.currentProject.title)
  const ts = Math.max(mediaCacheBuster.value, projectStore.mediaTimestamp || 0)
  if (hasVideoFile.value) {
    return `/api/media/${titleEnc}/video?t=${ts}`
  }
  return `/api/media/${titleEnc}/instrumental?t=${ts}`
})

const vocalsUrl = computed(() => {
  if (!projectStore.currentProject?.title) return ''
  return `/api/media/${encodeURIComponent(projectStore.currentProject.title)}/vocals?t=${mediaCacheBuster.value}`
})

const coverUrl = computed(() => {
  if (!projectStore.currentProject?.title) return ''
  return `/api/media/${encodeURIComponent(projectStore.currentProject.title)}/cover?t=${projectStore.coverTimestamp}`
})

function formatTime(sec: number): string {
  if (!sec || isNaN(sec) || sec < 0) sec = 0
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  const cs = Math.floor((sec % 1) * 100)
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}.${cs.toString().padStart(2, '0')}`
}

function handleTimeUpdate() {
  if (videoRef.value) {
    playerStore.onTimeUpdate(videoRef.value.currentTime)
  }
}

function handleLoadedMetadata() {
  playerStore.bindMedia(videoRef.value, audioRef.value)
}

function handleVideoEnded() {
  playerStore.pause()
}

function toggleMute() {
  isMuted.value = !isMuted.value
  playerStore.setMasterVolume(isMuted.value ? 0 : 1.0)
}

function onVideoStageClick() {
  playerStore.togglePlay()
}

function toggleLeadVocalQuick() {
  if (playerStore.liveVocalMultiplier > 0) {
    lastVocalMultiplier.value = playerStore.liveVocalMultiplier
    playerStore.setLiveVocalMultiplier(0)
  } else {
    playerStore.setLiveVocalMultiplier(lastVocalMultiplier.value || 0.8)
  }
}

function onMasterVolumeChange(e: Event) {
  const val = Number((e.target as HTMLInputElement).value) / 100
  isMuted.value = val === 0
  playerStore.setMasterVolume(val)
}

function onVocalMultiplierChange(e: Event) {
  const val = Number((e.target as HTMLInputElement).value) / 100
  if (val > 0) {
    lastVocalMultiplier.value = val
  }
  playerStore.setLiveVocalMultiplier(val)
}

function jumpToSelectionStart() {
  if (playerStore.selStart !== null) {
    playerStore.seek(playerStore.selStart)
  } else {
    playerStore.seek(0)
  }
}

// Global hotkeys (Space for play/pause)
function handleKeyDown(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
    return
  }
  if (e.code === 'Space') {
    e.preventDefault()
    playerStore.togglePlay()
  }
}

watch(
  [() => videoRef.value, () => audioRef.value],
  ([v, a]) => {
    playerStore.bindMedia(v, a)
  },
  { immediate: true }
)

watch(
  [() => projectStore.currentProject?.title, () => projectStore.currentProject?.has_video],
  async ([newTitle, newHasVideo], [oldTitle, oldHasVideo]) => {
    if (newTitle !== oldTitle || newHasVideo !== oldHasVideo) {
      mediaCacheBuster.value = Date.now()
      playerStore.resetForNewProject()
      await nextTick()
      if (videoRef.value) {
        try {
          videoRef.value.load()
        } catch (_) {}
      }
      if (audioRef.value) {
        try {
          audioRef.value.load()
        } catch (_) {}
      }
      playerStore.bindMedia(videoRef.value, audioRef.value)
    }
  }
)

watch(
  () => projectStore.mediaTimestamp,
  async (newTs, oldTs) => {
    if (newTs && newTs !== oldTs) {
      mediaCacheBuster.value = newTs
      await nextTick()
      if (videoRef.value) {
        try {
          videoRef.value.load()
        } catch (_) {}
      }
      if (audioRef.value) {
        try {
          audioRef.value.load()
        } catch (_) {}
      }
      playerStore.bindMedia(videoRef.value, audioRef.value)
    }
  }
)

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<template>
  <div class="flex-1 flex flex-col bg-studio-bg overflow-hidden min-h-0 border-r border-studio-border">
    <!-- Video Stage / Canvas Area -->
    <div class="flex-1 flex items-center justify-center p-3 relative overflow-hidden bg-black/60">
      <div
        v-if="projectStore.hasProject"
        @click="onVideoStageClick"
        class="relative w-full max-w-4xl max-h-full aspect-video flex items-center justify-center rounded-xl overflow-hidden shadow-2xl border border-slate-700/70 bg-slate-950 cursor-pointer group select-none"
        title="Нажмите для воспроизведения / паузы (Пробел)"
      >
        <video
          ref="videoRef"
          :src="videoUrl"
          :poster="coverUrl"
          preload="auto"
          @loadedmetadata="handleLoadedMetadata"
          @timeupdate="handleTimeUpdate"
          @ended="handleVideoEnded"
          class="w-full h-full object-contain pointer-events-none"
          playsinline
        ></video>

        <!-- Hover Play/Pause Quick Action Badge -->
        <div
          class="absolute inset-0 flex items-center justify-center bg-black/15 opacity-0 group-hover:opacity-100 transition-opacity duration-150 pointer-events-none"
        >
          <div class="w-14 h-14 rounded-full bg-slate-900/85 backdrop-blur-md border border-white/20 flex items-center justify-center shadow-2xl text-white transform group-hover:scale-105 transition-transform">
            <Pause v-if="playerStore.isPlaying" class="w-6 h-6 fill-current" />
            <Play v-else class="w-6 h-6 fill-current ml-0.5" />
          </div>
        </div>

        <!-- Sleek Preview Card when MP4 is not rendered yet (Audio Stems only) -->
        <div
          v-if="!hasVideoFile"
          class="absolute inset-0 flex flex-col items-center justify-center p-6 text-center select-none pointer-events-none overflow-hidden"
        >
          <img
            :src="coverUrl"
            alt=""
            class="absolute inset-0 w-full h-full object-cover opacity-25 blur-2xl scale-110"
          />
          <div class="relative z-10 flex flex-col items-center max-w-md bg-slate-900/80 backdrop-blur-md border border-slate-700/80 rounded-2xl px-6 py-5 shadow-2xl">
            <img
              :src="coverUrl"
              alt="Cover"
              class="w-24 h-24 rounded-xl object-cover shadow-lg border border-white/10 mb-3"
            />
            <div class="text-sm font-semibold text-slate-100 truncate max-w-xs">
              {{ projectStore.currentProject?.title }}
            </div>
            <span class="mt-1.5 inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30">
              Режим аудио-разметки (Stems готовы)
            </span>
            <p class="text-xs text-slate-400 mt-2 leading-relaxed">
              Плеер воспроизводит инструментал и вокал напрямую. Нажмите <strong class="text-emerald-400">«Пересобрать MP4»</strong> сверху для рендера видео.
            </p>
          </div>
        </div>

        <!-- Synced dry vocal track -->
        <audio
          ref="audioRef"
          :src="vocalsUrl"
          preload="auto"
          @loadedmetadata="handleLoadedMetadata"
        ></audio>
      </div>

      <div v-else class="text-center text-studio-muted">
        <Mic2 class="w-16 h-16 mx-auto mb-3 opacity-30 animate-pulse text-sky-400" />
        <p class="text-sm font-medium">Нет открытого проекта</p>
        <p class="text-xs text-slate-500 mt-1">Выберите трек из списка сверху или создайте новый</p>
      </div>
    </div>

    <!-- Transport & Mixer Bar -->
    <div class="h-14 bg-studio-panel border-t border-studio-border px-4 flex items-center justify-between shrink-0 select-none">
      <!-- Left: Playback controls -->
      <div class="flex items-center space-x-3">
        <button
          @click="playerStore.togglePlay()"
          :disabled="!projectStore.hasProject"
          class="w-9 h-9 rounded-full flex items-center justify-center bg-sky-600 hover:bg-sky-500 text-white shadow transition-all disabled:opacity-40"
        >
          <Pause v-if="playerStore.isPlaying" class="w-4 h-4 fill-current" />
          <Play v-else class="w-4 h-4 fill-current ml-0.5" />
        </button>

        <button
          @click="jumpToSelectionStart"
          :disabled="!projectStore.hasProject"
          title="В начало выделения"
          class="p-2 rounded text-slate-300 hover:text-white hover:bg-studio-surface disabled:opacity-30 transition-colors"
        >
          <SkipBack class="w-4 h-4" />
        </button>

        <button
          @click="playerStore.toggleLoop()"
          :class="[
            'p-2 rounded text-xs flex items-center space-x-1 border transition-colors',
            playerStore.isLooping
              ? 'bg-sky-600/30 border-sky-500 text-sky-300'
              : 'border-studio-border text-studio-muted hover:text-white hover:bg-studio-surface'
          ]"
          title="Зациклить воспроизведение выделения"
        >
          <Repeat class="w-4 h-4" />
        </button>

        <!-- Timecode Display -->
        <div class="font-mono text-sm tracking-wider text-slate-200 bg-studio-surface px-2.5 py-1 rounded border border-studio-border/70">
          <span class="text-sky-400 font-semibold">{{ formatTime(playerStore.currentTime) }}</span>
          <span class="text-studio-muted mx-1">/</span>
          <span class="text-slate-400">{{ formatTime(projectStore.duration) }}</span>
        </div>
      </div>

      <!-- Right: Audio Mix Controls -->
      <div class="flex items-center space-x-5">
        <!-- Live Vocal Multiplier (Practice Lead Vocals) -->
        <div
          class="flex items-center space-x-2"
          title="Подмешивание оригинального голоса в динамики для разучивания (0% = чистый минус). Нажмите на иконку микрофона для быстрого включения/выключения."
        >
          <button
            type="button"
            @click="toggleLeadVocalQuick"
            class="p-1 rounded transition-colors"
            :class="playerStore.effectiveVocalMultiplier > 0 ? 'text-emerald-400 bg-emerald-500/15' : 'text-slate-400 hover:text-emerald-300'"
            title="Вкл / Выкл лид-вокал"
          >
            <Mic2 class="w-4 h-4 shrink-0" />
          </button>
          <span
            @click="toggleLeadVocalQuick"
            class="text-xs text-slate-300 whitespace-nowrap cursor-pointer hover:text-white"
          >
            Лид-вокал:
          </span>
          <input
            type="range"
            min="0"
            max="150"
            step="5"
            :value="Math.round(playerStore.liveVocalMultiplier * 100)"
            @input="onVocalMultiplierChange"
            class="w-24 h-1.5 bg-slate-700 rounded-lg cursor-pointer"
          />
          <span
            class="text-xs font-mono w-10 text-right font-semibold"
            :class="playerStore.effectiveVocalMultiplier > 0 ? 'text-emerald-400' : 'text-slate-500'"
          >
            {{ Math.round(playerStore.effectiveVocalMultiplier * 100) }}%
          </span>
        </div>

        <div class="h-4 w-px bg-studio-border"></div>

        <!-- Master Volume -->
        <div class="flex items-center space-x-2">
          <button @click="toggleMute" class="text-slate-400 hover:text-white transition-colors">
            <VolumeX v-if="isMuted || playerStore.masterVolume === 0" class="w-4 h-4 text-red-400" />
            <Volume2 v-else class="w-4 h-4 text-slate-300" />
          </button>
          <input
            type="range"
            min="0"
            max="100"
            :value="Math.round(playerStore.masterVolume * 100)"
            @input="onMasterVolumeChange"
            class="w-20 h-1.5 bg-slate-700 rounded-lg cursor-pointer"
          />
        </div>
      </div>
    </div>
  </div>
</template>
